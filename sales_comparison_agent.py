import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime
import time
import traceback

# --- Setup Google Sheets API ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def load_gsheet(sheet_url):
    json_creds = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(json_creds, scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.sheet1
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

def summarize_internal_data(df):
    df['Internet'] = df['Product Name'].str.contains("INT", case=False, na=False).astype(int)
    df['TV'] = df['Product Name'].str.contains("TV", case=False, na=False).astype(int)
    df['Phone'] = df['Product Name'].str.contains("HP", case=False, na=False).astype(int)
    summary = df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()
    return summary

def normalize_client_data(df):
    df['Internet'] = df['Internet'].apply(lambda x: 1 if str(x).strip() else 0)
    df['TV'] = df['TV'].apply(lambda x: 1 if str(x).strip() else 0)
    df['Phone'] = df['Phone'].apply(lambda x: 1 if str(x).strip() else 0)
    return df

def compare_sales(internal_df, client_df):
    merged = pd.merge(internal_df, client_df, on='Account Number', how='left', suffixes=('_int', '_client'))
    mismatches = merged[(merged['Internet_int'] != merged['Internet_client']) |
                        (merged['TV_int'] != merged['TV_client']) |
                        (merged['Phone_int'] != merged['Phone_client']) |
                        (merged['Internet_client'].isnull())]
    return mismatches

st.set_page_config(page_title="Sales Comparison Agent", layout="wide")
st.markdown("""
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        .sidebar .sidebar-content {
            padding: 1rem;
        }
    </style>
""", unsafe_allow_html=True)

st.title("📊 Sales Comparison AI Agent")

with st.sidebar:
    st.header("🔧 Upload & Configure")
    uploaded_file = st.file_uploader("📤 Upload Internal Sales CSV", type=["csv"])
    sheet_url = st.text_input("🔗 Client Google Sheet URL")
    date_filter = st.date_input("📅 Filter by Sale Date", value=None)
    run_button = st.button("🚀 Run Comparison")

progress_placeholder = st.empty()

if uploaded_file and sheet_url and date_filter and run_button:
    try:
        progress_bar = progress_placeholder.progress(0, text="Initializing...")

        internal_raw = pd.read_csv(uploaded_file)
        progress_bar.progress(20, text="🔍 Validating internal data...")

        if 'Date of Sale' not in internal_raw.columns or 'Account Number' not in internal_raw.columns:
            st.error("❌ Required columns 'Date of Sale' or 'Account Number' not found in CSV.")
            st.stop()

        internal_raw['Date of Sale'] = pd.to_datetime(internal_raw['Date of Sale'], errors='coerce')
        internal_raw = internal_raw[internal_raw['Date of Sale'].dt.date == date_filter]
        summarized_internal = summarize_internal_data(internal_raw)
        progress_bar.progress(50, text="📦 Internal data processed.")

        with st.spinner("📥 Loading client sheet data..."):
            client_df = load_gsheet(sheet_url)
            client_df = normalize_client_data(client_df)
        progress_bar.progress(75, text="📊 Client data normalized.")

        st.markdown("### 🧾 Internal Data Summary")
        st.dataframe(summarized_internal)

        st.markdown("### 📄 Client Sheet (Normalized)")
        st.dataframe(client_df)

        mismatches = compare_sales(summarized_internal, client_df)
        progress_bar.progress(100, text="✅ Comparison complete!")
        time.sleep(0.5)
        progress_placeholder.empty()

        st.subheader("🔍 Mismatched Accounts Found")
        if mismatches.empty:
            st.success("🎉 All records match correctly for the selected date!")
        else:
            st.dataframe(mismatches, use_container_width=True)
            st.download_button("⬇️ Download Mismatches as CSV", mismatches.to_csv(index=False), "mismatches.csv")

    except Exception as e:
        st.error("⚠️ An unexpected error occurred during processing.")
        st.code(traceback.format_exc(), language='python')
else:
    st.info("ℹ️ Upload a CSV file, paste the Google Sheet URL, and select a date to begin.")
