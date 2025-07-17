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

# --- Region Detection ---
def detect_region(account_number):
    if account_number.startswith('500') and len(account_number) == 11:
        return 'ON'
    elif account_number.startswith('960') and len(account_number) == 12:
        return 'QC'
    elif account_number.startswith('833') and len(account_number) == 16:
        return 'US'
    return None

# --- Load and Combine All PSU Reports ---
def load_all_regions(sheet_url):
    json_creds = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(json_creds, scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)

    region_tabs = {
        'ON': 'PSUReport ON',
        'QC': 'PSUReport QC',
        'US': 'PSUReport US'
    }

    column_map = {
        'ON': {
            'Account Number': 'Billing Account Number',
            'Internet': 'Internet',
            'TV': 'TV',
            'Phone': 'Phone',
            'Date': 'Day of First Submit Date',
            'SO Status': 'SO Status'
        },
        'QC': {
            'Account Number': 'Billing Account Number',
            'Internet': 'Internet',
            'TV': 'TV',
            'Phone': 'Phone',
            'Date': 'Jour de First Submit Date',
            'SO Status': 'SO Status'
        },
        'US': {
            'Account Number': 'Account No',
            'Internet': 'Hsd Type',
            'TV': 'Video Type',
            'Phone': 'Phone Type',
            'Date': 'Open Date',
            'SO Status': 'Order Status'
        }
    }

    expected_cols = ['Account Number', 'Internet', 'TV', 'Phone', 'Date', 'SO Status', 'Region']
    all_data = []

    for region, tab in region_tabs.items():
        worksheet = sheet.worksheet(tab)
        rows = worksheet.get_all_values()
        headers = rows[0]
        df = pd.DataFrame(rows[1:], columns=headers)

        mapping = column_map[region]
        df = df.rename(columns={v: k for k, v in mapping.items()})
        df = df[list(mapping.values())]  # keep only mapped columns

        for col in ['Internet', 'TV', 'Phone']:
            if col not in df.columns:
                df[col] = ""

        df['Account Number'] = (
            df['Account Number']
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Region'] = region

        for col in expected_cols:
            if col not in df.columns:
                df[col] = None

        df = df[expected_cols]
        all_data.append(df)

    full_df = pd.concat(all_data, ignore_index=True)
    return full_df

# === Internal sales processing, product matching, mismatch logic, UI, and results display ===

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

def match_product(product, keywords):
    return any(k == str(product) for k in keywords)

def summarize_internal_data(df):
    df['Account Number'] = (
        df['Account Number']
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    df['Internet'] = df['Product Name'].apply(lambda x: int(match_product(x, INTERNET_KEYWORDS)))
    df['TV'] = df['Product Name'].apply(lambda x: int(match_product(x, TV_KEYWORDS)))
    df['Phone'] = df['Product Name'].apply(lambda x: int(match_product(x, PHONE_KEYWORDS)))

    summarized = df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()
    return summarized

def compare_sales(internal_df, client_df, start_date, end_date):
    internal_df['Account Number'] = internal_df['Account Number'].astype(str)
    client_df['Account Number'] = client_df['Account Number'].astype(str)

    merged = pd.merge(internal_df, client_df, on='Account Number', how='left', suffixes=('_YESA', '_Client'))

    reasons = []
    for _, row in merged.iterrows():
        acct = row['Account Number']
        if pd.isna(row['Internet_Client']) and pd.isna(row['TV_Client']) and pd.isna(row['Phone_Client']):
            reasons.append("Missing from report")
        elif not (row['Internet_YESA'] == row['Internet_Client'] and row['TV_YESA'] == row['TV_Client'] and row['Phone_YESA'] == row['Phone_Client']):
            reasons.append("PSU - no match")
        elif not pd.isnull(row['Date']):
            if not (start_date <= row['Date'].date() <= end_date):
                reasons.append("Missing from report - Wrong date")
            else:
                reasons.append(None)
        else:
            reasons.append(None)

    merged['Reason'] = reasons
    mismatches = merged[merged['Reason'].notnull()]

    duplicates = mismatches['Account Number'].value_counts()
    mismatches['Reason'] = mismatches.apply(
        lambda row: row['Reason'] + " (addon)" if duplicates[row['Account Number']] > 1 else row['Reason'], axis=1
    )

    return mismatches

# === Streamlit UI ===
st.markdown("## 📊 Upload Internal Sales Data")
col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader("📄 Upload Internal Sales CSV", type=["csv"])
with col2:
    sheet_url = st.text_input("🔗 Paste Client Google Sheet URL")

start_date, end_date = st.date_input("🗓 Select Date Range", [datetime.today(), datetime.today()])
run_button = st.button("🚀 Run Comparison")

if uploaded_file and sheet_url and run_button:
    try:
        internal_raw = pd.read_csv(uploaded_file)

        if 'Account Number' not in internal_raw.columns or 'Product Name' not in internal_raw.columns:
            st.error("❌ Required columns missing in internal file.")
            st.stop()

        summarized_internal = summarize_internal_data(internal_raw)
        st.success("✅ Internal data summarized.")

        client_df = load_all_regions(sheet_url)
        for col in ['Internet', 'TV', 'Phone']:
            client_df[col] = client_df[col].apply(lambda x: 1 if str(x).strip() else 0)

        mismatches = compare_sales(summarized_internal, client_df, start_date, end_date)

        st.subheader("📋 Mismatched Accounts")
        if mismatches.empty:
            st.success("🎉 All records matched!")
        else:
            show_cols = [
                "Reason", "Account Number", "Internet_YESA", "TV_YESA", "Phone_YESA",
                "Internet_Client", "TV_Client", "Phone_Client", "Date", "Region"
            ]
            st.dataframe(mismatches[show_cols], use_container_width=True)
            st.download_button("⬇️ Download Mismatches", mismatches[show_cols].to_csv(index=False), "mismatches.csv")

    except Exception as e:
        st.error(f"❌ Error occurred: {e}")
