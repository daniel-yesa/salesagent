import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import traceback

# --- Password Gate ---
st.markdown("## 🔒 Enter Access Password")
password = st.text_input("Password", type="password")
if password != "YESADATA":
    st.warning("🔐 Access restricted. Enter the correct password to continue.")
    st.stop()

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
uploaded_file = st.file_uploader("\U0001F4C4 Upload Booked Sales CSV", type=["csv"])
default_url = "https://docs.google.com/spreadsheets/d/1tamMxhdJ-_wuyCrmu9mK6RiVj1lZsUJBSm0gSBbjQwM/edit?gid=1075311190#gid=1075311190"
sheet_url = st.text_input("\U0001F517 Paste Google Sheet URL (Merged PSUReport)", value=default_url)
start_date, end_date = st.date_input("\U0001F4C5 Select Date Range", [datetime.today(), datetime.today()])
appealer_name = st.text_input("🧾 Name of Appealer (required)")

if uploaded_file and not appealer_name.strip():
    st.warning("⚠️ Please enter your name before running the report.")

if uploaded_file:
    st.session_state['uploaded_file'] = uploaded_file
elif 'uploaded_file' in st.session_state:
    uploaded_file = st.session_state['uploaded_file']

run_button = st.button("\U0001F680 Run Missing Report")

if uploaded_file and sheet_url and run_button:
    with st.spinner("Processing..."):
        try:
            internal_df = pd.read_csv(uploaded_file)
            internal_df['Date of Sale'] = pd.to_datetime(internal_df['Date of Sale'], errors='coerce')
            internal_df = internal_df[
                (internal_df['Date of Sale'] >= pd.to_datetime(start_date)) &
                (internal_df['Date of Sale'] <= pd.to_datetime(end_date))
            ]
            internal_df['Account Number'] = internal_df['Account Number'].astype(str).str.strip()

            internal_df['Internet'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, INTERNET_KEYWORDS)))
            internal_df['TV'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, TV_KEYWORDS)))
            internal_df['Phone'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, PHONE_KEYWORDS)))

            summarized = internal_df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()

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
            psu_df['Account Number'] = psu_df['Account Number'].astype(str).str.strip()
            psu_df['Date of Sale'] = pd.to_datetime(psu_df['Date of Sale'], errors='coerce')
            for col in ['Internet', 'TV', 'Phone']:
                psu_df[col] = psu_df[col].apply(lambda x: 1 if str(x).strip() else 0)
            psu_df = psu_df.set_index("Account Number")

            mismatches = []
            total_checked = 0
            progress = st.progress(0)

            for idx, row in summarized.iterrows():
                acct = row['Account Number']
                if acct.startswith("833"):
                    continue
                total_checked += 1
                progress.progress(min(total_checked / len(summarized), 1.0))

                if acct not in psu_df.index:
                    mismatches.append({'Account Number': acct, 'Reason': 'Missing from report'})
                    continue

                psu_rows = psu_df.loc[[acct]] if acct in psu_df.index else pd.DataFrame()
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
            st.subheader("\U0001F4CB Mismatched Accounts")
            st.metric("Total Checked", total_checked)
            st.metric("Mismatches Found", len(result_df))

        if result_df.empty:
            st.success("\U0001F389 All records matched!")
        else:
            st.dataframe(result_df, use_container_width=True)
            today_str = datetime.today().strftime("%B %d %Y")
            st.download_button("⬇️ Download CSV", result_df.to_csv(index=False), file_name=f"Mismatched {today_str}.csv")

            # --- ⬇️ Generate Open Appeals table directly ---
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

                merged_df["Date of Sale_x"] = pd.to_datetime(merged_df["Date of Sale_x"], errors="coerce")
                merged_df["Scheduled Install Date"] = pd.to_datetime(merged_df["Scheduled Install Date"], errors="coerce")
                today_mmddyyyy = datetime.today().strftime("%m/%d/%Y")

                appeals_df = pd.DataFrame({
                    "Type of Appeal": ["Open"] * len(merged_df),
                    "Name of Appealer": [appealer_name] * len(merged_df),
                    "Date of Appeal": [today_mmddyyyy] * len(merged_df),
                    "Account number": merged_df["Account Number"],
                    "Customer Address": merged_df.apply(format_address, axis=1),
                    "City": merged_df["City"],
                    "Date Of Sale": merged_df["Date of Sale_x"].dt.strftime("%m/%d/%Y"),
                    "Sales Rep": merged_df["Sale Rep"],
                    "Rep ID": merged_df["Rep Id"],
                    "Install Type": merged_df["Self Install"].apply(install_type),
                    "Installation Date": merged_df["Scheduled Install Date"].dt.strftime("%m/%d/%Y"),
                    "Internet": merged_df["Internet_YESA"].apply(lambda x: 1 if x == 1 else ""),
                    "TV": merged_df["TV_YESA"].apply(lambda x: 1 if x == 1 else ""),
                    "Phone": merged_df["Phone_YESA"].apply(lambda x: 1 if x == 1 else ""),
                    "Reason for Appeal": merged_df["Reason"].apply(map_reason),
                })

                appeals_df = appeals_df.drop_duplicates(subset=["Account number"])

                st.subheader("📄 Open Appeals Table")
                st.dataframe(appeals_df, use_container_width=True)

                st.download_button(
                    label="⬇️ Download Appeals CSV",
                    data=appeals_df.to_csv(index=False),
                    file_name=f"Open_Appeals {today_str}.csv"
                )

            except Exception as e:
                st.error("❌ Failed to generate Open Appeals table.")
                if debug_mode:
                    st.exception(e)
