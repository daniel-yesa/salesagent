import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time
import json
import io

# --- Setup Google Sheets API ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
log = []

# --- App Branding ---
st.set_page_config(page_title="MatchMate | YESA", layout="wide")
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap');
        html, body, [class*="css"]  {
            font-family: 'Poppins', sans-serif;
            color: #1f1f1f;
            background-color: #f4f6f8;
        }
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 1000px;
            margin: auto;
        }
        h1, h2, h3, h4 {
            font-weight: 600;
            color: #2e2e2e;
        }
        .metric-box {
            padding: 1.5rem; border-radius: 14px;
            background: linear-gradient(135deg, #d4f1ff 0%, #ffffff 100%);
            box-shadow: 0 6px 16px rgba(0,0,0,0.05);
            text-align: center; font-size: 1.1rem;
            margin-bottom: 1rem;
            animation: fadeIn 0.5s ease-in-out;
        }
        @keyframes fadeIn {
            from {opacity: 0; transform: translateY(10px);}
            to {opacity: 1; transform: translateY(0);}
        }
        .metric-title {
            color: #6a6a6a;
            font-size: 0.85rem;
        }
        .metric-value {
            font-weight: 700;
            font-size: 1.6rem;
            color: #005b96;
        }
        .stFileUploader {
            max-width: 320px !important;
            margin: auto;
        }
        .stButton > button {
            background: linear-gradient(to right, #3f87a6, #ebf8e1);
            color: #222;
            font-weight: 600;
            border: none;
            border-radius: 6px;
            padding: 0.5rem 1rem;
            transition: 0.3s;
        }
        .stButton > button:hover {
            background: linear-gradient(to right, #005b96, #cce6ff);
            transform: scale(1.02);
        }
        .dataframe td {
            font-size: 14px;
        }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
    <h1 style='text-align: center; font-size: 3rem;'>✨ MatchMate</h1>
    <p style='text-align: center; color: #555; font-size: 18px;'>
        The most powerful and elegant way to compare YESA internal sales with client records.
    </p>
    <hr style='margin-top: 0.5rem;'>
""", unsafe_allow_html=True)

# --- App Logic ---
def load_gsheet(sheet_url):
    json_creds = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(json_creds, scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet("PSUReport")
    rows = worksheet.get_all_values()
    headers = rows[0]
    df = pd.DataFrame(rows[1:], columns=headers)
    df["Billing Account Number"] = df["Billing Account Number"].astype(str).str.strip()
    df.rename(columns={"Billing Account Number": "Account Number"}, inplace=True)
    for col in ["Internet", "TV", "Phone"]:
        if col not in df.columns:
            df[col] = ""
    return df

INTERNET_KEYWORDS = ["1 Gig", "500 Mbps", "200 Mbps", "100 Mbps", "UltraFibre 60 - Unlimited", "UltraFibre 90 - Unlimited", "UltraFibre 120 - Unlimited", "UltraFibre 180 - Unlimited", "UltraFibre 360 - Unlimited", "UltraFibre 1Gig - Unlimited", "UltraFibre 2Gig - Unlimited"]
TV_KEYWORDS = ["Stream Box", "Family +", "Variety +", "Entertainment +", "Locals +", "Supreme package", "epico x-stream", "epico plus", "epico intro", "epico basic"]
PHONE_KEYWORDS = ["Freedom", "Basic", "Landline Phone"]

def match_product(product, keywords):
    return any(k == str(product) for k in keywords)

def summarize_internal_data(df):
    df["Account Number"] = df["Account Number"].astype(str).str.strip()
    df['Internet'] = df['Product Name'].apply(lambda x: int(match_product(x, INTERNET_KEYWORDS)))
    df['TV'] = df['Product Name'].apply(lambda x: int(match_product(x, TV_KEYWORDS)))
    df['Phone'] = df['Product Name'].apply(lambda x: int(match_product(x, PHONE_KEYWORDS)))
    return df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()

def normalize_client_data(df):
    df['Internet'] = df['Internet'].apply(lambda x: 1 if str(x).strip() else 0)
    df['TV'] = df['TV'].apply(lambda x: 1 if str(x).strip() else 0)
    df['Phone'] = df['Phone'].apply(lambda x: 1 if str(x).strip() else 0)
    return df

def compare_sales(internal_df, client_df, start_date, end_date):
    internal_df['Account Number'] = internal_df['Account Number'].astype(str)
    client_df['Account Number'] = client_df['Account Number'].astype(str)
    merged = pd.merge(internal_df, client_df, on='Account Number', how='left', suffixes=('_YESA', '_Client'))
    
    date_columns = ['Day of First Submit Date', 'Open Date', 'Jour de First Submit Date']
    date_column_found = next((col for col in date_columns if col in client_df.columns), None)
    if date_column_found:
        client_df[date_column_found] = pd.to_datetime(client_df[date_column_found], errors='coerce')
        account_all_dates = client_df.groupby('Account Number')[date_column_found].apply(list).to_dict()
        account_date_map = client_df.set_index('Account Number')[date_column_found].to_dict()
    else:
        account_all_dates = {}
        account_date_map = {}

    def reason_logic(row):
        acct = row['Account Number']
        client_date = account_date_map.get(acct)
        all_dates = account_all_dates.get(acct, [])
        products_missing = all(pd.isnull(row.get(f + '_Client')) for f in ['Internet', 'TV', 'Phone'])

        if acct not in account_date_map or products_missing:
            return "Missing from report"
        if any(row.get(f + '_YESA') != row.get(f + '_Client') for f in ['Internet', 'TV', 'Phone']):
            return "PSU - no match"
        if all(pd.notnull(d) and not (start_date <= d.date() <= end_date) for d in all_dates):
            return "Missing from report - Wrong date"
        return None

    merged['Reason'] = merged.apply(reason_logic, axis=1)
    mismatches = merged[merged['Reason'].notnull()]
    addon_accounts = mismatches['Account Number'].value_counts()
    mismatches['Reason'] = mismatches.apply(
        lambda row: row['Reason'] + " (addon)" if addon_accounts[row['Account Number']] > 1 else row['Reason'], axis=1
    )
    return mismatches

# --- Streamlit UI ---
st.markdown("### ⚙️ Configure Comparison")
with st.container():
    with st.form("config_form"):
        col1, col2, col3 = st.columns([1.5, 1, 1])
        uploaded_file = col1.file_uploader("Internal Sales CSV or Excel", type=["csv", "xlsx"])
        sheet_url = col2.text_input("Client Google Sheet URL")
        with col3:
            start_date = st.date_input("Start Date")
            end_date = st.date_input("End Date")
        submitted = st.form_submit_button("🚀 Run Comparison")

if uploaded_file and sheet_url and start_date and end_date and submitted:
    try:
        progress = st.progress(0, text="Processing...")
        internal_raw = pd.read_csv(uploaded_file) if uploaded_file.name.endswith("csv") else pd.read_excel(uploaded_file)

        if 'Date of Sale' not in internal_raw.columns:
            st.error("❌ 'Date of Sale' column missing in internal file.")
            st.stop()

        internal_raw['Date of Sale'] = pd.to_datetime(internal_raw['Date of Sale'], errors='coerce')
        filtered_internal = internal_raw[
            (internal_raw['Date of Sale'].dt.date >= start_date) & (internal_raw['Date of Sale'].dt.date <= end_date)
        ]
        summarized_internal = summarize_internal_data(filtered_internal)
        client_df = normalize_client_data(load_gsheet(sheet_url))
        mismatches = compare_sales(summarized_internal, client_df, start_date, end_date)

        progress.progress(100, text="✅ Done!")
        st.markdown("---")

        colA, colB = st.columns(2)
        colA.markdown(f"<div class='metric-box'><div class='metric-title'>Mismatches</div><div class='metric-value'>{len(mismatches)}</div></div>", unsafe_allow_html=True)
        colB.markdown(f"<div class='metric-box'><div class='metric-title'>Accounts Processed</div><div class='metric-value'>{summarized_internal.shape[0]}</div></div>", unsafe_allow_html=True)

        st.markdown("### 📋 Mismatched Accounts")
        if mismatches.empty:
            st.success("🎉 All records matched for this date range!")
        else:
            def color_reason(val):
                if 'addon' in val:
                    return 'color: orange'
                elif 'no match' in val:
                    return 'color: red'
                elif 'wrong date' in val:
                    return 'color: purple'
                elif 'Missing' in val:
                    return 'color: darkred'
                return ''

            show_cols = ["Reason", "Account Number", "Internet_YESA", "TV_YESA", "Phone_YESA", "Account Number", "Internet_Client", "TV_Client", "Phone_Client"]
            styled = mismatches[show_cols].style.applymap(color_reason, subset=['Reason'])
            st.dataframe(styled, use_container_width=True)
            st.download_button("⬇️ Download Mismatch Report", mismatches[show_cols].to_csv(index=False), "mismatches.csv")

    except Exception as e:
        st.exception(e)
        st.error(f"⚠️ An error occurred: {str(e)}")
else:
    st.info("ℹ️ Upload a file, paste a sheet URL, and select a date range to get started.")
