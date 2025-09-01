# mapping_utils_new.py

import re
import json
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- Fallback and Filename functions remain the same ---
def get_fallback_mappings():
    # This function is unchanged
    return {"brand_mappings": {"fallback_3_brand": {'q7_1': 'AU', 'q7_2': 'DJ', 'q7_3': 'HH', '1': 'AU', '2': 'DJ', '3': 'HH', 'Q12b_1': 'AU', 'Q12b_2': 'DJ', 'Q12b_3': 'HH'}, "fallback_4_brand": {'q7_1': 'DB', 'q7_2': 'DJ', 'q7_3': 'HH', 'q7_4': 'PK', '1': 'DB', '2': 'DJ', '3': 'HH', '4': 'PK', 'Q12b_1': 'DB', 'Q12b_2': 'DJ', 'Q12b_3': 'HH', 'Q12b_4': 'PK'}}, "imagery_mappings": {'Q6a.1': 'City Paper', 'Q6a.2': 'Market Leader', 'Q6a.3': 'Trustworthy', 'Q6a.4': 'Buzz (Charcha)', 'Q6a.5': 'Good quantum', 'Q6a.6': 'Latest local news', 'Q6a.7': 'Raises issues/ concerns', 'Q6a.8': 'Changes with time', 'Q6a.9': 'Complete analysis', 'Q6a.10': 'Appeals to Everyone', 'Q6a.11': 'Good Discount / Good Schemes', 'Q6a.12': 'Unbiased and bold', 'Q6a.13': 'Best On Education And Employment', 'Q6a.14': 'Content different from other newspapers', 'Q6a.15': 'Brand is Ready for Future', 'Q6a.16': 'Appeals Youth', 'Q6a.17': 'Offers News in both Print & Digital formats', 'Q6a.18': 'Premium Brand'}, "sectional_mappings": {'1': 'Front Page', '2': 'State Polit', '3': 'Local', '4': 'Education/Campus', '5': 'Nearby (Aaspaas)', '6': 'State/Pradesh', '7': 'Business', '8': 'International news', '9': 'National News', '10': 'Sports'}}

def get_brand_mapping_from_filename(filename, mappings_data):
    # This function is unchanged
    clean_filename = filename.replace('.xlsx', '') if filename else filename
    if not clean_filename or not mappings_data: return None
    brand_mappings = mappings_data.get("brand_mappings", {})
    if clean_filename in brand_mappings: return brand_mappings[clean_filename]
    for key in brand_mappings:
        if key in clean_filename or clean_filename in key: return brand_mappings[key]
    return None

# --- NEW AND MODIFIED FUNCTIONS ---

@st.cache_resource
def connect_to_gdrive():
    """Connects to Google Drive using Streamlit secrets and returns both gspread and drive_service clients."""
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"])
        scoped_creds = creds.with_scopes(["https://www.googleapis.com/auth/drive.readonly"])
        gc = gspread.authorize(scoped_creds)
        drive_service = build('drive', 'v3', credentials=scoped_creds)
        return gc, drive_service
    except Exception as e:
        st.error(f"Failed to connect to Google Drive: {e}")
        return None, None

@st.cache_data(ttl=600)
def load_mappings_from_json(_drive_service): # <-- Underscore added here
    """Loads mappings from brand_mappings.json stored in Google Drive."""
    if _drive_service is None: return get_fallback_mappings()
    try:
        folder_id = st.secrets["gdrive"]["folder_id"]
        # The variable below is also updated to use the underscore
        query = f"'{folder_id}' in parents and name='brand_mappings.json' and trashed=false"
        results = _drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files:
            st.error("brand_mappings.json not found in the specified Google Drive folder.")
            return get_fallback_mappings()

        mapping_file_id = files[0]['id']
        # The variable below is also updated to use the underscore
        file_content = _drive_service.files().get_media(fileId=mapping_file_id).execute()
        mappings = json.loads(file_content)

        required_keys = ["brand_mappings", "imagery_mappings", "sectional_mappings"]
        if not all(key in mappings for key in required_keys):
            st.error("Mapping file is missing required keys.")
            return get_fallback_mappings()
        return mappings
    except Exception as e:
        st.error(f"Error loading brand_mappings.json from Google Drive: {e}")
        return get_fallback_mappings()

def apply_mappings(df, original_df, filename=None, drive_service=None):
    """Applies brand mappings loaded from Google Drive."""
    if df.empty: return df
    df_mapped = df.copy()
    mappings_data = load_mappings_from_json(drive_service)
    # ... rest of the function is the same ...
    imagery_map = mappings_data["imagery_mappings"]
    sectional_map = mappings_data["sectional_mappings"]
    brand_map_to_use = get_brand_mapping_from_filename(filename, mappings_data)
    if brand_map_to_use is None:
        original_cols_lower = [str(c).lower() for c in original_df.columns]
        is_4_brand = any(col.strip().startswith('q7_4') for col in original_cols_lower)
        fallback_mappings = mappings_data["brand_mappings"]
        brand_map_to_use = fallback_mappings.get("fallback_4_brand" if is_4_brand else "fallback_3_brand", {})
    brand_map_lower = {k.lower(): v for k, v in brand_map_to_use.items()}
    imagery_map_lower = {k.lower(): v for k, v in imagery_map.items()}
    sectional_map_lower = {k.lower(): v for k, v in sectional_map.items()}
    full_map = {**brand_map_lower, **imagery_map_lower, **sectional_map_lower}
    sorted_keys = sorted(full_map.keys(), key=len, reverse=True)
    new_columns = {}
    for col_name in df_mapped.columns:
        new_name = str(col_name)
        for key in sorted_keys:
            new_name = re.sub(re.escape(key), full_map[key], new_name, flags=re.IGNORECASE)
        new_columns[col_name] = new_name
    df_mapped.rename(columns=new_columns, inplace=True)
    for col_name in ['Paper', 'Brand']:
        if col_name in df_mapped.columns:
            def map_composite_value(value):
                s_val = str(value).strip()
                if ' - ' in s_val:
                    parts = [p.strip() for p in s_val.split(' - ')]
                    mapped_parts = [brand_map_lower.get(p.lower(), p) for p in parts]
                    return ' - '.join(mapped_parts)
                return brand_map_lower.get(s_val.lower(), s_val)
            df_mapped[col_name] = df_mapped[col_name].apply(map_composite_value)
    if 'Question' in df_mapped.columns:
        df_mapped['Question'] = df_mapped['Question'].apply(lambda x: imagery_map_lower.get(str(x).strip().lower(), x))
    if 'Q No.' in df_mapped.columns:
        df_mapped['Q No.'] = df_mapped['Q No.'].astype(str).apply(lambda x: sectional_map_lower.get(x.strip().lower(), x))
    return df_mapped