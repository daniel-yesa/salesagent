import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import traceback

# --- Streamlit UI ---
st.set_page_config(page_title="Findr | YESA", layout="wide")
st.markdown("""
    <style>
        html, body, [class*="css"] {
            background-color: #f2f2f2 !important;
        }
    </style>
""", unsafe_allow_html=True)
st.title("🔎 Findr - Accounts Missing / PSU no match")
debug_mode = st.checkbox("🔍 Enable Debug Mode")

# --- Keywords ---
INTERNET_KEYWORDS = [
    "1 Gig", "500 Mbps", "200 Mbps", "100 Mbps",
    "UltraFibre 60 - Unlimited", "UltraFibre 90 - Unlimited",
    "UltraFibre 120 - Unlimited", "UltraFibre 180 - Unlimited",
    "UltraFibre 360 - Unlimited", "UltraFibre 1Gig - Unlimited",
    "UltraFibre 2Gig - Unlimited"
]
TV_KEYWORDS = [
    "Stream Box", "Family +", "Variety +", "Entertainment +", "Locals +",
    "Supreme package", "epico x-stream", "epico plus", "epico intro", "epico basic"
]
PHONE_KEYWORDS = ["Freedom", "Basic", "Landline Phone"]

def match_product(name, keywords):
    return any(k == str(name).strip() for k in keywords)

# --- Inputs ---
uploaded_file = st.file_uploader("📄 Upload Booked Sales CSV", type=["csv"])
default_url = "https://docs.google.com/spreadsheets/d/1tamMxhdJ-_wuyCrmu9mK6RiVj1lZsUJBSm0gSBbjQwM/edit?gid=1075311190#gid=1075311190"
sheet_url = st.text_input("🔗 Paste Google Sheet URL (Merged PSUReport)", value=default_url)
start_date, end_date = st.date_input("🗓 Select Date Range", [datetime.today(), datetime.today()])

# --- Preview Sheet ---
if sheet_url:
    try:
        creds = Credentials.from_service_account_info(
            json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]),
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        )
        sheet = gspread.authorize(creds).open_by_url(sheet_url)

        try:
            worksheet = sheet.worksheet("Merged PSUReport")
        except gspread.exceptions.WorksheetNotFound:
            st.error("❌ Could not find tab named 'Merged PSUReport'")
            if debug_mode:
                st.write("🗂 Tabs available:", [ws.title for ws in sheet.worksheets()])
            st.stop()

        rows = worksheet.get_all_values()
        headers = rows[0]
        psu_preview = pd.DataFrame(rows[1:], columns=headers)
        psu_preview.columns = psu_preview.columns.str.strip()

        st.markdown("### 📋 Preview: Merged PSUReport (First 10 Rows)")
        st.dataframe(psu_preview.head(10), use_container_width=True)

        if st.checkbox("🔎 Show full PSU sheet preview"):
            st.dataframe(psu_preview, use_container_width=True)

    except Exception as e:
        st.error("❌ Failed to preview PSU sheet.")
        if debug_mode:
            st.exception(e)

run_button = st.button("🚀 Run Missing Report")

# --- Main ---
if uploaded_file and sheet_url and run_button:
    with st.spinner("Processing..."):
        try:
            # Load internal sales
            internal_df = pd.read_csv(uploaded_file)
            internal_df['Date of Sale'] = pd.to_datetime(internal_df['Date of Sale'], errors='coerce')
            internal_df = internal_df[
                (internal_df['Date of Sale'] >= pd.to_datetime(start_date)) &
                (internal_df['Date of Sale'] <= pd.to_datetime(end_date))
            ]

            internal_df['Account Number'] = internal_df['Account Number'].astype(str).str.strip()

            # Product matching
            internal_df['Internet'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, INTERNET_KEYWORDS)))
            internal_df['TV'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, TV_KEYWORDS)))
            internal_df['Phone'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, PHONE_KEYWORDS)))

            summarized = internal_df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()

            # Load and clean PSU sheet
            creds = Credentials.from_service_account_info(
                json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            )
            sheet = gspread.authorize(creds).open_by_url(sheet_url)
            worksheet = sheet.worksheet("Merged PSUReport")
            rows = worksheet.get_all_values()
            headers = rows[0]
            psu_df = pd.DataFrame(rows[1:], columns=headers)
            psu_df.columns = [col.strip() for col in psu_df.columns]

            if debug_mode:
                st.write("🧠 Columns in PSU sheet:", list(psu_df.columns))

            # Resolve account number column
            account_col = next((col for col in psu_df.columns if col.strip().lower() == "account number"), None)
            if not account_col:
                st.error("❌ 'Account Number' column not found in PSU sheet.")
                if debug_mode:
                    st.write("🗂 Available columns:", list(psu_df.columns))
                st.stop()

            psu_df.rename(columns={account_col: "Account Number"}, inplace=True)
            psu_df["Account Number"] = psu_df["Account Number"].astype(str).str.strip()

            # Validate other required columns
            required_cols = ["Date of Sale", "Internet", "TV", "Phone"]
            missing_cols = [col for col in required_cols if col not in psu_df.columns]
            if missing_cols:
                st.error(f"❌ Missing columns in PSU sheet: {missing_cols}")
                if debug_mode:
                    st.write("🧩 All PSU columns:", list(psu_df.columns))
                st.stop()

            # Convert data
            psu_df['Date of Sale'] = pd.to_datetime(psu_df['Date of Sale'], errors='coerce')
            for col in ['Internet', 'TV', 'Phone']:
                psu_df[col] = psu_df[col].apply(lambda x: 1 if str(x).strip() else 0)
            psu_df = psu_df.set_index("Account Number")

            # Compare
            mismatches = []
            total_checked = 0
            progress = st.progress(0)

            for idx, row in summarized.iterrows():
                acct = row['Account Number']
                if acct.startswith("833"):
                    continue  # ⛔️ Skip US accounts
                acct = row['Account Number']
                total_checked += 1
                progress.progress(min(total_checked / len(summarized), 1.0))

                if acct not in psu_df.index:
                    mismatches.append({'Account Number': acct, 'Reason': 'Missing from report'})
                    continue

                # Get all PSU rows for the account
                psu_rows = psu_df.loc[[acct]] if acct in psu_df.index else pd.DataFrame()
                
                # Filter PSU rows within the selected date range
                psu_rows_in_range = psu_rows[
                    psu_rows['Date of Sale'].notna() &
                    (psu_rows['Date of Sale'].dt.date >= start_date) &
                    (psu_rows['Date of Sale'].dt.date <= end_date)
                ]
                
                reason = None
                psu = None
                
                if not psu_rows_in_range.empty:
                    combined = psu_rows_in_range[['Internet', 'TV', 'Phone']].max()
                    if not (
                        combined['Internet'] == row['Internet'] and
                        combined['TV'] == row['TV'] and
                        combined['Phone'] == row['Phone']
                    ):
                        reason = "PSU - no match"
                        psu = psu_rows_in_range.iloc[0]
                else:
                    reason = "Wrong date"
                    psu = psu_rows.iloc[0] if not psu_rows.empty else None

                if reason and psu is not None:
                    mismatches.append({
                        'Account Number': acct,
                        'Reason': reason,
                        'Internet_YESA': row['Internet'],
                        'TV_YESA': row['TV'],
                        'Phone_YESA': row['Phone'],
                        'Client Account': acct,
                        'Internet_Client': psu['Internet'],
                        'TV_Client': psu['TV'],
                        'Phone_Client': psu['Phone'],
                        'Date': psu['Date of Sale']
                    })

            result_df = pd.DataFrame(mismatches)
            st.subheader("📋 Mismatched Accounts")
            st.metric("Total Checked", total_checked)
            st.metric("Mismatches Found", len(result_df))

            if result_df.empty:
                st.success("🎉 All records matched!")
            else:
                st.dataframe(result_df, use_container_width=True)
                today_str = datetime.today().strftime("%B %d %Y")  # e.g. "July 17 2025"
                filename = f"Mismatched {today_str}.csv"

                st.download_button("⬇️ Download CSV", result_df.to_csv(index=False), file_name=filename)
            # --- After displaying mismatches ---
            if not result_df.empty:
                if st.button("📄 Generate General Appeals"):
                    with st.spinner("Generating Open Appeals..."):
                        try:
                            merged_df = pd.merge(result_df, internal_df, on="Account Number", how="left")
            
                            def format_address(row):
                                addr = row.get("Customer Address", "")
                                addr2 = row.get("Customer Address Line 2", "")
                                return f"{addr}, {addr2}" if pd.notna(addr2) and addr2.strip() else addr
            
                            def install_type(val):
                                return "Self Install" if str(val).strip().lower() == "yes" else "Tech Visit"
            
                            def map_reason(reason):
                                if reason == "Missing from report":
                                    return "Account missing from report"
                                if reason == "PSU - no match":
                                    return "PSUs don't match report"
                                return ""
            
                            open_appeals = pd.DataFrame({
                                "Account number": merged_df["Account Number"],
                                "Customer Address": merged_df.apply(format_address, axis=1),
                                "City": merged_df["City"],
                                "Date Of Sale": merged_df["Date of Sale"],
                                "Sales Rep": merged_df["Sale Rep"],
                                "Rep ID": merged_df["Rep Id"],
                                "Install Type": merged_df["Self Install"].apply(install_type),
                                "Installation Date": merged_df["Scheduled Install Date"],
                                "Internet": merged_df["Internet_YESA"].apply(lambda x: 1 if x == 1 else ""),
                                "TV": merged_df["TV_YESA"].apply(lambda x: 1 if x == 1 else ""),
                                "Phone": merged_df["Phone_YESA"].apply(lambda x: 1 if x == 1 else ""),
                                "Reason for Appeal": merged_df["Reason"].apply(map_reason),
                            })
            
                            st.subheader("📄 General Appeals Table")
                            st.dataframe(open_appeals, use_container_width=True)
            
                            today_str = datetime.today().strftime("%B %d %Y")
                            appeal_filename = f"Open_Appeals {today_str}.csv"
                            st.download_button("⬇️ Download Appeals CSV", open_appeals.to_csv(index=False), file_name=appeal_filename)
            
                        except Exception as e:
                            st.error("❌ Failed to generate appeals table.")
                            if debug_mode:
                                st.exception(e)

        except Exception as e:
            st.error("❌ Error occurred during processing.")
            st.exception(e)
            if debug_mode:
                st.code(traceback.format_exc(), language="python")
