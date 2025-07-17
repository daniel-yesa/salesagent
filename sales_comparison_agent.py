# matchmate_merged_app.py
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import traceback

# --- Streamlit UI ---
st.set_page_config(page_title="MatchMate | Merged PSU", layout="wide")
st.title("✨ MatchMate - Merged PSUReport Comparison")
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
uploaded_file = st.file_uploader("📄 Upload Internal Sales CSV", type=["csv"])
sheet_url = st.text_input("🔗 Paste Google Sheet URL (Merged PSUReport)")
start_date, end_date = st.date_input("🗓 Select Date Range", [datetime.today(), datetime.today()])
run_button = st.button("🚀 Run Comparison")

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

            # Load Merged PSUReport
            creds = Credentials.from_service_account_info(
                json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            )
            sheet = gspread.authorize(creds).open_by_url(sheet_url)
            worksheet = sheet.worksheet("Merged PSUReport")
            rows = worksheet.get_all_values()
            headers = rows[0]
            psu_df = pd.DataFrame(rows[1:], columns=headers)

            psu_df['Account Number'] = psu_df['Account Number'].astype(str).str.strip()
            psu_df['Date of Sale'] = pd.to_datetime(psu_df['Date of Sale'], errors='coerce')

            for col in ['Internet', 'TV', 'Phone']:
                psu_df[col] = psu_df[col].apply(lambda x: 1 if str(x).strip() else 0)

            psu_df = psu_df.set_index('Account Number')

            # Match
            mismatches = []
            total_checked = 0
            progress = st.progress(0)

            for idx, row in summarized.iterrows():
                acct = row['Account Number']
                total_checked += 1
                progress.progress(min(total_checked / len(summarized), 1.0))

                if acct not in psu_df.index:
                    mismatches.append({'Account Number': acct, 'Reason': 'Missing from report'})
                    continue

                psu = psu_df.loc[acct]
                reason = None
                if not (psu['Internet'] == row['Internet'] and psu['TV'] == row['TV'] and psu['Phone'] == row['Phone']):
                    reason = "PSU - no match"
                elif pd.notna(psu['Date of Sale']) and not (start_date <= psu['Date of Sale'].date() <= end_date):
                    reason = "Wrong date"

                if reason:
                    mismatches.append({
                        'Account Number': acct,
                        'Reason': reason,
                        'Internet_YESA': row['Internet'],
                        'TV_YESA': row['TV'],
                        'Phone_YESA': row['Phone'],
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
                st.download_button("⬇️ Download CSV", result_df.to_csv(index=False), "mismatches.csv")

        except Exception as e:
            st.error("❌ Error occurred during processing.")
            st.exception(e)
            if debug_mode:
                st.code(traceback.format_exc(), language="python")
