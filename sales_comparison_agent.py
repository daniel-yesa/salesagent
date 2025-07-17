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

# --- Load Correct Sheet Based on Region ---
def load_gsheet(sheet_url, region):
    json_creds = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(json_creds, scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)

    tab_map = {
        'ON': 'PSUReport ON',
        'QC': 'PSUReport QC',
        'US': 'PSUReport US'
    }
    region_tab = tab_map.get(region)
    if not region_tab:
        raise ValueError(f"Unsupported region for sheet tab lookup: {region}")

    worksheet = sheet.worksheet(region_tab)
    rows = worksheet.get_all_values()
    headers = rows[0]
    df = pd.DataFrame(rows[1:], columns=headers)

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

    region_cols = column_map[region]
    df = df.rename(columns={v: k for k, v in region_cols.items()})
    for col in ['Internet', 'TV', 'Phone']:
        if col not in df.columns:
            df[col] = ""
    df['Account Number'] = df['Account Number'].astype(str).str.strip()
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    return df

# --- Upload UI & Run ---
with st.expander("📥 Upload Internal Sales File & Connect Sheet", expanded=True):
    uploaded_file = st.file_uploader("Upload Internal Sales CSV or Excel", type=["csv", "xlsx"])
    sheet_url = st.text_input("Paste Client Google Sheet URL")
    date_range = st.date_input("Select Date Range for Comparison", [])
    run_button = st.button("🚀 Run MatchMate")

if uploaded_file and sheet_url and date_range and run_button:
    try:
        content = uploaded_file.read().decode("utf-8") if uploaded_file.name.endswith(".csv") else uploaded_file
        internal_df = pd.read_csv(io.StringIO(content)) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)

        if "Account Number" not in internal_df.columns:
            if "Billing Account Number" in internal_df.columns:
                internal_df.rename(columns={"Billing Account Number": "Account Number"}, inplace=True)
            elif "Account No" in internal_df.columns:
                internal_df.rename(columns={"Account No": "Account Number"}, inplace=True)
            else:
                st.error("❌ Internal file is missing 'Account Number', 'Billing Account Number', or 'Account No' column.")
                st.stop()

        internal_df['Account Number'] = (
            internal_df['Account Number']
            .astype(str)
            .str.strip()
            .str.replace(r"\\.0$", "", regex=True)
        )

        account_sample = internal_df['Account Number'].dropna().tolist()
        st.write("🔍 First 10 Account Numbers:", account_sample[:10])

        region = None
        for acct in account_sample:
            region = detect_region(acct)
            if region:
                break

        if not region:
            st.error("❌ Could not detect region from account number format.")
            st.stop()

        client_df = load_gsheet(sheet_url, region)
        st.success(f"✅ Loaded PSUReport for {region}")
        st.write(client_df.head())

        # --- Resume Comparison Pipeline Here ---

        # Filter internal by date range
        if 'Date of Sale' not in internal_df.columns:
            st.error("❌ Internal file must contain a 'Date of Sale' column.")
            st.stop()

        internal_df['Date of Sale'] = pd.to_datetime(internal_df['Date of Sale'], errors='coerce')
        internal_df = internal_df[internal_df['Date of Sale'].between(pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]))]

        # Extract product indicators
        INTERNET_KEYWORDS = ["1 Gig", "500 Mbps", "200 Mbps", "100 Mbps", "UltraFibre 60 - Unlimited", "UltraFibre 90 - Unlimited", "UltraFibre 120 - Unlimited", "UltraFibre 180 - Unlimited", "UltraFibre 360 - Unlimited", "UltraFibre 1Gig - Unlimited", "UltraFibre 2Gig - Unlimited"]
        TV_KEYWORDS = ["Stream Box", "Family +", "Variety +", "Entertainment +", "Locals +", "Supreme package", "epico x-stream", "epico plus", "epico intro", "epico basic"]
        PHONE_KEYWORDS = ["Freedom", "Basic", "Landline Phone"]

        def match_product(product, keywords):
            return any(k == str(product) for k in keywords)

        internal_df['Internet'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, INTERNET_KEYWORDS)))
        internal_df['TV'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, TV_KEYWORDS)))
        internal_df['Phone'] = internal_df['Product Name'].apply(lambda x: int(match_product(x, PHONE_KEYWORDS)))

                internal_df['Account Number'] = (
            internal_df['Account Number']
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )
        summarized_internal = internal_df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()

        # Normalize client data
        for col in ['Internet', 'TV', 'Phone']:
            client_df[col] = client_df[col].apply(lambda x: 1 if str(x).strip() else 0)

        # Aggregate client data by Account Number + SO Status
        client_df['SO Status'] = client_df['SO Status'].fillna('')
        grouped_client = client_df.groupby(['Account Number', 'SO Status'])[['Internet', 'TV', 'Phone']].max().reset_index()
        latest_status_map = client_df.dropna(subset=['Date']).sort_values('Date').drop_duplicates('Account Number', keep='last').set_index('Account Number')['SO Status'].to_dict()

        def get_best_match(account):
            status = latest_status_map.get(account, '')
            subset = grouped_client[(grouped_client['Account Number'] == account) & (grouped_client['SO Status'] == status)]
            if not subset.empty:
                return subset.iloc[0][['Internet', 'TV', 'Phone']].tolist()
            return [None, None, None]

        comparison = summarized_internal.copy()
        comparison[['Internet_Client', 'TV_Client', 'Phone_Client']] = comparison['Account Number'].apply(lambda acct: pd.Series(get_best_match(acct)))

        def determine_reason(row):
            acct = row['Account Number']
            client_rows = client_df[client_df['Account Number'] == acct]
            if client_rows.empty or (client_rows[['Internet', 'TV', 'Phone']].sum(axis=1) == 0).all():
                return "Missing from report"
            if pd.isnull(row['Internet_Client']) and pd.isnull(row['TV_Client']) and pd.isnull(row['Phone_Client']):
                return "Missing from report"
            if (row['Internet_YESA'], row['TV_YESA'], row['Phone_YESA']) != (row['Internet_Client'], row['TV_Client'], row['Phone_Client']):
                return "PSU - no match"
            client_dates = client_rows['Date'].dropna()
            if not client_dates.empty:
                in_range = client_dates.between(pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])).any()
                if not in_range:
                    return "Missing from report - wrong date"
            return None

        comparison = comparison.rename(columns={"Internet": "Internet_YESA", "TV": "TV_YESA", "Phone": "Phone_YESA"})
        comparison['Reason'] = comparison.apply(determine_reason, axis=1)

        duplicate_counts = comparison['Account Number'].value_counts()
        comparison['Reason'] = comparison.apply(lambda row: f"{row['Reason']} (addon)" if duplicate_counts[row['Account Number']] > 1 and pd.notnull(row['Reason']) else row['Reason'], axis=1)

        mismatches = comparison[comparison['Reason'].notnull()]

        st.subheader("📋 Mismatched Accounts")
        if mismatches.empty:
            st.success("🎉 All records matched correctly for the selected date range!")
        else:
            display_cols = ['Reason', 'Account Number', 'Internet_YESA', 'TV_YESA', 'Phone_YESA', 'Internet_Client', 'TV_Client', 'Phone_Client']
            st.dataframe(mismatches[display_cols], use_container_width=True)
            st.download_button("⬇️ Download Mismatches", mismatches[display_cols].to_csv(index=False), "mismatches.csv")

    except Exception as e:
        st.error(f"Error: {e}")
