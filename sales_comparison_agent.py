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

log = []  # For debugging log

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

    if "Billing Account Number" not in df.columns:
        raise ValueError(f"❌ Column 'Billing Account Number' is missing from PSUReport tab. Found columns: {debug_headers}")

    df["Billing Account Number"] = df["Billing Account Number"].astype(str).str.strip()
    df.rename(columns={"Billing Account Number": "Account Number"}, inplace=True)

    for col in ["Internet", "TV", "Phone"]:
        if col not in df.columns:
            df[col] = ""

    return df

# --- Product extraction for internal data ---
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
    return any(k == str(product) for k in keywords)  # strict case-sensitive match

def summarize_internal_data(df):
    debug_internal_headers = list(df.columns)
    if "Billing Account Number" in df.columns and "Account Number" not in df.columns:
        df.rename(columns={"Billing Account Number": "Account Number"}, inplace=True)

    if "Account Number" not in df.columns:
        raise ValueError(f"❌ The internal data must contain an 'Account Number' column. Found columns: {debug_internal_headers}")

    df["Account Number"] = df["Account Number"].astype(str).str.strip()

    df['Internet'] = df['Product Name'].apply(lambda x: int(match_product(x, INTERNET_KEYWORDS)))
    df['TV'] = df['Product Name'].apply(lambda x: int(match_product(x, TV_KEYWORDS)))
    df['Phone'] = df['Product Name'].apply(lambda x: int(match_product(x, PHONE_KEYWORDS)))

    summary = df.groupby('Account Number')[['Internet', 'TV', 'Phone']].max().reset_index()
    return summary

# --- Normalize client data ---
def normalize_client_data(df):
    df['Internet'] = df['Internet'].apply(lambda x: 1 if str(x).strip() else 0)
    df['TV'] = df['TV'].apply(lambda x: 1 if str(x).strip() else 0)
    df['Phone'] = df['Phone'].apply(lambda x: 1 if str(x).strip() else 0)
    return df

# --- Comparison logic ---
def compare_sales(internal_df, client_df, date_filter):
    internal_df['Account Number'] = internal_df['Account Number'].astype(str)
    client_df['Account Number'] = client_df['Account Number'].astype(str)

    merged = pd.merge(internal_df, client_df, on='Account Number', how='left', suffixes=('_YESA', '_Client'))
    merged['Client Account Number'] = merged['Account Number']  # duplicate for clarity

    log.append(f"🔍 Merging {len(internal_df)} internal rows with {len(client_df)} client rows")

    # Identify possible date columns
    date_columns = ['Day of First Submit Date', 'Open Date', 'Jour de First Submit Date']
    date_column_found = next((col for col in date_columns if col in client_df.columns), None)

    if date_column_found:
        client_df[date_column_found] = pd.to_datetime(client_df[date_column_found], errors='coerce')
        account_date_map = client_df.set_index('Account Number')[date_column_found].to_dict()
    else:
        account_date_map = {}

    def reason_logic(row):
        client_in_sheet = row['Account Number'] in client_df['Account Number'].values
        matched_date = False
        if client_in_sheet and row['Account Number'] in account_date_map:
            client_date = account_date_map[row['Account Number']]
            if pd.notnull(client_date):
                input_date_str = date_filter.strftime('%-m/%-d/%Y')
                matched_date = (
                    client_date.strftime('%-m/%-d/%Y') == input_date_str or
                    client_date.strftime('%#m/%#d/%Y') == input_date_str or
                    client_date.strftime('%m/%d/%Y') == input_date_str
                )

        if pd.isnull(row['Internet_Client']) and matched_date:
            return "Missing from report"
        elif pd.isnull(row['Internet_Client']) and not matched_date:
            return "Missing from report - wrong day"
        elif row['Internet_YESA'] != row['Internet_Client'] or row['TV_YESA'] != row['TV_Client'] or row['Phone_YESA'] != row['Phone_Client']:
            return "PSU - no match"
        else:
            return None

    merged['Reason'] = merged.apply(reason_logic, axis=1)
    mismatches = merged[merged['Reason'].notnull()]
    return mismatches

# --- Streamlit UI ---
st.set_page_config(page_title="Sales Comparison Agent", layout="centered")
st.title("💼 Sales Comparison Agent")
st.write("Easily validate internal sales data with client-reported records.")

with st.expander("🔧 Configure and Run", expanded=True):
    uploaded_file = st.file_uploader("📄 Upload Internal Sales CSV or Excel", type=["csv", "xlsx"])
    sheet_url = st.text_input("🔗 Paste Client Google Sheet URL", value="https://docs.google.com/spreadsheets/d/1tamMxhdJ-_wuyCrmu9mK6RiVj1lZsUJBSm0gSBbjQwM/edit?gid=1075311190")
    date_filter = st.date_input("🗕️ Choose Sale Date", value=None)
    if date_filter:
        st.caption(f"📅 You selected: {date_filter.strftime('%-m/%-d/%Y')}")
    run_button = st.button("🚀 Run Data Comparison")

progress_placeholder = st.empty()

if uploaded_file and sheet_url and date_filter and run_button:
    try:
        progress_bar = progress_placeholder.progress(0, text="⏳ Starting comparison...")

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
        filtered_internal = internal_raw[internal_raw['Date of Sale'].dt.date == date_filter]
        summarized_internal = summarize_internal_data(filtered_internal)
        st.write("✅ Internal Product Counts:", summarized_internal[['Internet', 'TV', 'Phone']].sum().to_dict())
        progress_bar.progress(50, text="✅ Internal data processed.")

        with st.spinner("📥 Loading client Google Sheet data..."):
            client_df = load_gsheet(sheet_url)
            client_df = normalize_client_data(client_df)
        progress_bar.progress(75, text="✅ Client data loaded.")

        mismatches = compare_sales(summarized_internal, client_df, date_filter)
        progress_bar.progress(100, text="🎯 Comparison complete!")
        time.sleep(0.5)
        progress_placeholder.empty()

        st.subheader("📋 Mismatched Accounts")
        if mismatches.empty:
            st.success("🎉 All records matched correctly for the selected date!")
        else:
            show_cols = [
                "Reason", "Account Number", "Internet_YESA", "TV_YESA", "Phone_YESA",
                "Client Account Number", "Internet_Client", "TV_Client", "Phone_Client"
            ]
            st.dataframe(mismatches[show_cols], use_container_width=True)
            st.download_button("⬇️ Download Results", mismatches[show_cols].to_csv(index=False), "mismatches.csv")

        if log:
            st.expander("🛠 Debug Log").write("\n".join(log))

    except Exception as e:
        st.exception(e)
        st.error(f"⚠️ An error occurred: {str(e)}")
else:
    st.info("ℹ️ Upload a CSV or Excel file, enter a Google Sheet URL, and select a date to start.")
