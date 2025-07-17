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

    all_data = []

    for region, tab in region_tabs.items():
        worksheet = sheet.worksheet(tab)
        rows = worksheet.get_all_values()
        headers = rows[0]
        df = pd.DataFrame(rows[1:], columns=headers)

        mapping = column_map[region]
        df = df.rename(columns={v: k for k, v in mapping.items()})

        for col in ['Internet', 'TV', 'Phone']:
            if col not in df.columns:
                df[col] = ""

        df['Account Number'] = (
            df['Account Number']
            .astype(str)
            .str.strip()
            .str.replace(r"\\.0$", "", regex=True)
        )

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Region'] = region

        # Standardize column order before merging
        expected_cols = ['Account Number', 'Internet', 'TV', 'Phone', 'Date', 'SO Status', 'Region']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None
        df = df[expected_cols]

        all_data.append(df)

    full_df = pd.concat(all_data, ignore_index=True)
    return full_df

# --- App Input UI ---
with st.expander("🔧 Configure and Run", expanded=True):
    uploaded_file = st.file_uploader("📄 Upload Internal Sales CSV or Excel", type=["csv", "xlsx"])
    sheet_url = st.text_input("🔗 Paste Client Google Sheet URL", value="")
    date_range = st.date_input("📅 Choose Sale Date Range", value=(datetime.today(), datetime.today()))
    run_button = st.button("🚀 Run Data Comparison")

# --- Validate and Compare ---
if uploaded_file and sheet_url and run_button:
    if isinstance(date_range, tuple):
        start_date, end_date = date_range
    else:
        st.error("❌ Please select a date range.")
        st.stop()

    if uploaded_file.name.endswith(".csv"):
        internal_raw = pd.read_csv(uploaded_file)
    else:
        internal_raw = pd.read_excel(uploaded_file)

    internal_raw['Account Number'] = (
        internal_raw['Account Number']
        .astype(str)
        .str.strip()
        .str.replace(r"\\.0$", "", regex=True)
    )

    internal_raw = internal_raw[internal_raw['Account Number'].notna()]

    with st.spinner("📥 Loading client Google Sheet data..."):
        client_df = load_all_regions(sheet_url)

    st.success("✅ PSU Reports Loaded")
    st.write(client_df.head())
