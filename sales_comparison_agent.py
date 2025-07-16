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

def load_gsheet(sheet_url):
    json_creds = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(json_creds, scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)

    sheet_titles = [ws.title for ws in sheet.worksheets()]
    st.info(f"📄 Sheets found in workbook: {sheet_titles}")

    if "PSUReport" in sheet_titles:
        worksheet = sheet.worksheet("PSUReport")
    else:
        raise ValueError(f"❌ 'PSUReport' tab not found. Found tabs: {sheet_titles}")

    rows = worksheet.get_all_values()
    header_row_index = next((i for i, row in enumerate(rows) if any(cell.strip() for cell in row)), 0)
    headers = rows[header_row_index]
    data_rows = rows[header_row_index + 1:]

    df = pd.DataFrame(data_rows, columns=headers)

    debug_headers = list(df.columns)
    st.text(f"🔍 PSUReport Headers Detected: {debug_headers}")

    if "Billing Account Number" in df.columns:
        df.rename(columns={"Billing Account Number": "Account Number"}, inplace=True)

    if "Account Number" not in df.columns:
        raise ValueError(f"❌ Column 'Account Number' is missing from PSUReport tab. Found columns: {debug_headers}")

    df["Account Number"] = df["Account Number"].astype(str).str.strip()

    for col in ["Internet", "TV", "Phone"]:
        if col not in df.columns:
            df[col] = ""

    return df

# --- Product extraction for internal data ---
def summarize_internal_data(df):
    debug_internal_headers = list(df.columns)
    if "Billing Account Number" in df.columns and "Account Number" not in df.columns:
        df.rename(columns={"Billing Account Number": "Account Number"}, inplace=True)

    if "Account Number" not in df.columns:
        raise ValueError(f"❌ The internal data must contain an 'Account Number' column. Found columns: {debug_internal_headers}")

    df["Account Number"] = df["Account Number"].astype(str).str.strip()

    df['Internet'] = df['Product Name'].str.contains("INT", case=False, na=False).astype(int)
    df['TV'] = df['Product Name'].str.contains("TV", case=False, na=False).astype(int)
    df['Phone'] = df['Product Name'].str.contains("HP", case=False, na=False).astype(int)
    summary = df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()
    return summary

# --- Normalize client data ---
def normalize_client_data(df):
    df['Internet'] = df['Internet'].apply(lambda x: 1 if str(x).strip() else 0)
    df['TV'] = df['TV'].apply(lambda x: 1 if str(x).strip() else 0)
    df['Phone'] = df['Phone'].apply(lambda x: 1 if str(x).strip() else 0)
    return df

# --- Comparison logic ---
def compare_sales(internal_df, client_df):
    internal_df['Account Number'] = internal_df['Account Number'].astype(str)
    client_df['Account Number'] = client_df['Account Number'].astype(str)

    merged = pd.merge(internal_df, client_df, on='Account Number', how='left', suffixes=('_int', '_client'))
    mismatches = merged[(merged['Internet_int'] != merged['Internet_client']) |
                        (merged['TV_int'] != merged['TV_client']) |
                        (merged['Phone_int'] != merged['Phone_client']) |
                        (merged['Internet_client'].isnull())]
    return mismatches

# --- Streamlit UI ---
st.set_page_config(page_title="Sales Comparison Agent", layout="centered")
st.markdown("""
    <style>
        .main {
            padding: 2rem;
            background-color: #f9f9f9;
        }
        .stButton>button {
            width: 100%;
            background-color: #4CAF50;
            color: white;
            font-weight: bold;
            border-radius: 6px;
            padding: 0.75rem;
            font-size: 16px;
        }
        .stFileUploader, .stDateInput, .stTextInput {
            margin-bottom: 1rem;
        }
        .css-1aumxhk, .css-1cpxqw2 {
            font-family: 'Segoe UI', sans-serif;
        }
    </style>
""", unsafe_allow_html=True)

st.title("💼 Sales Comparison Agent")
st.write("Easily validate internal sales data with client-reported records.")

with st.expander("🔧 Configure and Run", expanded=True):
    uploaded_file = st.file_uploader("📤 Upload Internal Sales CSV or Excel", type=["csv", "xlsx"])
    sheet_url = st.text_input("🔗 Paste Client Google Sheet URL")
    date_filter = st.date_input("📅 Choose Sale Date", value=None)
    run_button = st.button("🚀 Run Data Comparison")

if uploaded_file:
    try:
        if uploaded_file.name.endswith(".csv"):
            content = uploaded_file.read().decode("utf-8", errors="ignore")
            lines = [line for line in content.splitlines() if line.strip() != ""]
            preview_df = pd.read_csv(io.StringIO("\n".join(lines[:10])))
            uploaded_file.seek(0)
        else:
            preview_df = pd.read_excel(uploaded_file, nrows=10)

        if preview_df.empty or len(preview_df.columns) == 0:
            st.warning("⚠️ Uploaded file has no readable columns. Please check the format.")
        else:
            st.caption("🔍 Preview of Internal Data:")
            st.dataframe(preview_df)
    except Exception as e:
        st.error(f"⚠️ Could not preview file: {e}")

progress_placeholder = st.empty()

if uploaded_file and sheet_url and date_filter and run_button:
    try:
        progress_bar = progress_placeholder.progress(0, text="⏳ Starting comparison...")

        # Load and process internal data
        if uploaded_file.name.endswith(".csv"):
            content = uploaded_file.read().decode("utf-8", errors="ignore")
            lines = [line for line in content.splitlines() if line.strip() != ""]
            internal_raw = pd.read_csv(io.StringIO("\n".join(lines)))
        else:
            internal_raw = pd.read_excel(uploaded_file)

        progress_bar.progress(20, text="📄 Loading internal sales data...")

        if 'Date of Sale' not in internal_raw.columns:
            st.error("❌ File must contain a 'Date of Sale' column.")
            st.stop()

        internal_raw['Date of Sale'] = pd.to_datetime(internal_raw['Date of Sale'], errors='coerce')
        internal_raw = internal_raw[internal_raw['Date of Sale'].dt.date == date_filter]
        summarized_internal = summarize_internal_data(internal_raw)
        progress_bar.progress(50, text="✅ Internal data processed.")

        with st.spinner("📥 Loading client Google Sheet data..."):
            client_df = load_gsheet(sheet_url)
            client_df = normalize_client_data(client_df)
        progress_bar.progress(75, text="✅ Client data loaded.")

        mismatches = compare_sales(summarized_internal, client_df)
        progress_bar.progress(100, text="🎯 Comparison complete!")
        time.sleep(0.5)
        progress_placeholder.empty()

        st.subheader("📋 Mismatched Accounts")
        if mismatches.empty:
            st.success("🎉 All records matched correctly for the selected date!")
        else:
            st.dataframe(mismatches, use_container_width=True)
            st.download_button("⬇️ Download Results", mismatches.to_csv(index=False), "mismatches.csv")

    except Exception as e:
        st.exception(e)
        st.error(f"⚠️ An error occurred: {str(e)}")
else:
    st.info("ℹ️ Upload a CSV or Excel file, enter a Google Sheet URL, and select a date to start.")
