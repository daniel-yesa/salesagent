import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
from io import StringIO
from gspread_dataframe import get_as_dataframe

# --- Page Configuration ---
st.set_page_config(page_title="YESA Sales Comparison Tool", layout="wide")
st.title("📊 YESA Sales Comparison Agent")

st.markdown("""
Upload your internal YESA export CSV and provide the Google Sheets URL for the client's PSUReport.
This tool will match account numbers and product types (Internet, TV, Phone) and identify any mismatches.
""")

# --- Product Keyword Lists ---
INTERNET_KEYWORDS = [
    "1 Gig", "500 Mbps", "200 Mbps", "100 Mbps",
    "UltraFibre 60 - Unlimited", "UltraFibre 90 - Unlimited",
    "UltraFibre 120 - Unlimited", "UltraFibre 180 - Unlimited",
    "UltraFibre 360 - Unlimited", "UltraFibre 1Gig - Unlimited",
    "UltraFibre 2Gig - Unlimited"
]

TV_KEYWORDS = [
    "Stream Box", "Family +", "Variety +", " Entertainment +", "Locals +",
    "Supreme package", "epico x-stream", "epico plus", "epico intro", "epico basic"
]

PHONE_KEYWORDS = ["Freedom", "Basic", "Landline Phone"]

# --- Case-Sensitive Product Match ---
def match_product(product, keywords):
    return any(k in str(product) for k in keywords)

# --- Load Google Sheet ---
def load_gsheet(sheet_url):
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]), scope
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet("PSUReport")
    df = get_as_dataframe(worksheet, evaluate_formulas=True)
    df = df.dropna(how="all")
    return df

# --- Inputs ---
uploaded_file = st.file_uploader("📂 Upload YESA CSV Export", type="csv")
sheet_url = st.text_input(
    "🔗 Client Google Sheet URL",
    placeholder="https://docs.google.com/spreadsheets/d/.../edit"
)
date_filter = st.date_input("📅 Filter by Date of Sale")

# --- Process Data ---
if uploaded_file and sheet_url and date_filter:
    try:
        with st.spinner("Processing..."):
            df = pd.read_csv(uploaded_file)

            # Format the selected date for filtering
            selected_date = pd.to_datetime(date_filter).strftime("%m/%d/%Y")
            df = df[df["Date of Sale"] == selected_date]

            # Create binary columns for product categories
            df["Internet"] = df["Product Name"].apply(lambda x: 1 if match_product(x, INTERNET_KEYWORDS) else 0)
            df["TV"] = df["Product Name"].apply(lambda x: 1 if match_product(x, TV_KEYWORDS) else 0)
            df["Phone"] = df["Product Name"].apply(lambda x: 1 if match_product(x, PHONE_KEYWORDS) else 0)

            # Summarize to one row per account number
            summarized = df.groupby("Account Number")[["Internet", "TV", "Phone"]].max().reset_index()

            # Load client sheet and rename key column
            client_df = load_gsheet(sheet_url)
            client_df = client_df.rename(columns={"Billing Account Number": "Account Number"})

            # Merge and compare
            comparison = pd.merge(
                summarized,
                client_df,
                on="Account Number",
                how="left",
                suffixes=("_YESA", "_Client")
            )

            mismatches = []
            for _, row in comparison.iterrows():
                if pd.isna(row["Internet_Client"]):
                    mismatches.append({
                        "Account Number": row["Account Number"],
                        "Reason": "Missing from report"
                    })
                elif (
                    row["Internet_YESA"] != row["Internet_Client"]
                    or row["TV_YESA"] != row["TV_Client"]
                    or row["Phone_YESA"] != row["Phone_Client"]
                ):
                    mismatches.append({
                        "Account Number": row["Account Number"],
                        "Reason": "PSU - no match"
                    })

            if mismatches:
                st.error(f"❌ {len(mismatches)} mismatches found:")
                st.dataframe(pd.DataFrame(mismatches))
            else:
                st.success("✅ All records matched successfully!")

    except Exception as e:
        st.error(f"⚠️ An error occurred: {e}")
