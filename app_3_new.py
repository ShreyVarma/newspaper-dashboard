# app_3_new.py

import streamlit as st
import pandas as pd
import os
import numpy as np
from PIL import Image
import io
import gspread
from gspread_dataframe import get_as_dataframe

from mapping_utils_new import apply_mappings, connect_to_gdrive
from utils_V2_new import (dynamic_nps_analysis, compute_tom_from_q5a, compute_dynamic_imagery, sectional_nps, calculate_segmented_nps_with_sig)

st.set_page_config(page_title="Newspaper Dashboard", layout="wide", page_icon="📰")
st.markdown("""<style>.stDataFrame thead th {text-align: center;} .stDataFrame tbody td:not(:first-child) {text-align: center;}</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=600)
def list_gdrive_contents(_drive_service, folder_id):
    if _drive_service is None: return {}
    try:
        query = f"'{folder_id}' in parents and trashed = false"
        results = _drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        return {item['name']: {'id': item['id'], 'type': 'folder' if item['mimeType'] == 'application/vnd.google-apps.folder' else 'file'} for item in items}
    except Exception as e:
        st.error(f"Could not list Google Drive contents: {e}"); return {}

@st.cache_data(ttl=600)
def load_data(_drive_service, file_id):
    if _drive_service is None: return None
    try:
        request = _drive_service.files().get_media(fileId=file_id)
        df = pd.read_excel(io.BytesIO(request.execute()))
        return df.dropna(how='all')
    except Exception as e:
        st.error(f"An error occurred while loading file ID {file_id} from Google Drive: {e}"); return None

def display_styled_dataframe(title, calculated_df, original_df, index_col_name, filename=None, drive_service=None):
    st.subheader(title)
    if calculated_df is None or calculated_df.empty:
        st.warning(f"No data available to display for {title}."); return
    df_mapped = apply_mappings(calculated_df, original_df, filename, drive_service=drive_service)
    styler = None; display_df = df_mapped
    diff_cols = [col for col in df_mapped.columns if 'minus' in str(col)]
    if len(df_mapped) == 1 and diff_cols:
        score_cols = [c for c in df_mapped.columns if 'minus' not in str(c) and 'Z_' not in str(c) and 'Sig_' not in str(c) and c != index_col_name]
        scores_long = df_mapped[score_cols].melt(var_name='Newspapers', value_name='NPS Score')
        scores_long['is_sig'] = False
        diffs_long = df_mapped[diff_cols].melt(var_name='Newspapers', value_name='NPS Score')
        sig_map = {col.replace('Sig_', '').replace('_vs_', '_minus_'): (df_mapped[col].iloc[0] == 'Significant') for col in df_mapped.columns if col.startswith('Sig_')}
        diffs_long['is_sig'] = diffs_long['Newspapers'].map(sig_map).fillna(False)
        display_df = pd.concat([scores_long, diffs_long], ignore_index=True)
        display_df['Newspapers'] = display_df['Newspapers'].str.replace('_minus_', ' - ', regex=False)
        styler = display_df[['Newspapers', 'NPS Score']].style.apply(style_significant_column, significance_series=display_df['is_sig'], column_to_style='NPS Score', axis=None)
    elif diff_cols:
        cols_to_keep = [index_col_name] + diff_cols
        display_df = df_mapped[cols_to_keep]
        display_df.columns = [str(c).replace('_minus_', ' - ') for c in display_df.columns]
        styler = display_df.style.apply(style_difference_columns, full_df_with_sig_cols=df_mapped, axis=None)
    else:
        if 'TOM (%)' in display_df.columns and 'Brand' in display_df.columns:
            display_df = display_df.rename(columns={'Brand': 'Newspapers', 'TOM (%)': 'TOM Score'}); score_col = 'TOM Score'
        else: score_col = 'Score'
        is_significant = display_df['Significance'] == 'Significant' if 'Significance' in display_df.columns else pd.Series(False, index=display_df.index)
        styler = display_df.drop(columns=['Z Score', 'Significance'], errors='ignore').style.apply(style_significant_column, significance_series=is_significant, column_to_style=score_col, axis=None)
    def custom_formatter(x):
        return f"{x:.0f}" if isinstance(x, (float, int)) else x
    cols_to_format = [c for c in styler.data.columns if c not in [index_col_name, 'Paper', 'Brand', 'Question', 'Q No.', 'Segment', 'Newspapers'] and 'Sig_' not in str(c) and 'Z_' not in str(c)]
    st.dataframe(styler.format({col: custom_formatter for col in cols_to_format}), hide_index=True)

def style_significant_column(df, significance_series, column_to_style):
    styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if column_to_style not in df.columns: return styles
    numeric_series = pd.to_numeric(df[column_to_style], errors='coerce')
    styles.loc[significance_series & (numeric_series > 0), column_to_style] = 'background-color: lightgreen'
    styles.loc[significance_series & (numeric_series < 0), column_to_style] = 'background-color: lightcoral'
    return styles

def style_difference_columns(df_to_style, full_df_with_sig_cols):
    styler = pd.DataFrame('', index=df_to_style.index, columns=df_to_style.columns)
    original_diff_cols = [col for col in full_df_with_sig_cols.columns if 'minus' in str(col)]
    for original_diff_col in original_diff_cols:
        try:
            ref_brand, comp_brand = original_diff_col.split('_minus_')
            sig_col_name = f"Sig_{ref_brand}_vs_{comp_brand}"
            renamed_diff_col = original_diff_col.replace('_minus_', ' - ')
            if sig_col_name in full_df_with_sig_cols.columns and renamed_diff_col in df_to_style.columns:
                is_significant = full_df_with_sig_cols[sig_col_name] == 'Significant'
                numeric_diff_series = pd.to_numeric(df_to_style[renamed_diff_col], errors='coerce')
                styler.loc[is_significant & (numeric_diff_series > 0), renamed_diff_col] = 'background-color: lightgreen'
                styler.loc[is_significant & (numeric_diff_series < 0), renamed_diff_col] = 'background-color: lightcoral'
        except (IndexError, KeyError): continue
    return styler

def main_dashboard():
    st.sidebar.title("Newspaper Analysis Dashboard")
    gc, drive_service = connect_to_gdrive()
    if not gc or not drive_service: st.error("Could not connect to Google Drive."); st.stop()
    
    try:
        gdrive_folder_id = st.secrets["gdrive"]["folder_id"]
        root_contents = list_gdrive_contents(drive_service, gdrive_folder_id)
        data_new_folder_id = next((info['id'] for name, info in root_contents.items() if name == 'data_new' and info['type'] == 'folder'), None)
        if not data_new_folder_id: st.sidebar.error("A 'data_new' folder was not found."); st.stop()
        cities_dict = list_gdrive_contents(drive_service, data_new_folder_id)
        cities = sorted([name for name, info in cities_dict.items() if info['type'] == 'folder'])
        if not cities: st.sidebar.error("No city folders found."); st.stop()
    except Exception as e:
        st.sidebar.error(f"Failed to read from Google Drive: {e}"); st.stop()
    
    selected_city = st.sidebar.selectbox("Select City", cities)
    city_folder_id = cities_dict[selected_city]['id']
    waves_dict = list_gdrive_contents(drive_service, city_folder_id)
    waves = sorted([name for name, info in waves_dict.items() if info['type'] == 'file' and '.xls' in name])
    if not waves: st.sidebar.error(f"No data files found for {selected_city}."); st.stop()
    selected_waves = st.sidebar.multiselect("Select Waves", waves, default=waves)
    
    loaded_dataframes = {}
    if selected_waves:
        for wave_file in selected_waves:
            file_id = waves_dict[wave_file]['id']
            wave_key = os.path.splitext(wave_file)[0]
            loaded_dataframes[wave_key] = load_data(drive_service, file_id)
    else: st.sidebar.warning("Please select at least one wave."); st.stop()

    for df in loaded_dataframes.values():
        if df is not None:
            df.columns = [str(c).lower() for c in df.columns]
            if 'q1a' in df.columns: df['gender'] = df['q1a'].map({1: 'Male', 2: 'Female'})
            if 'sq1b' in df.columns: df['age_group'] = pd.cut(df['sq1b'], bins=[24, 34, 45], labels=['25–34', '35–45'], right=True)
            sec_col = next((c for c in ['sec', 'sech_cod'] if c in df.columns), None)
            if sec_col: df['nccs_group'] = df[sec_col].map(lambda x: 'NCCS A' if x in [1, 2, 3] else ('NCCS B+C' if x in [4, 5, 6, 7] else np.nan))

    st.sidebar.subheader("Apply Filters")
    first_df = next(iter(loaded_dataframes.values()), None)
    if first_df is not None:
        gender_options = ["All"] + sorted(first_df["gender"].dropna().unique()) if 'gender' in first_df.columns else ["All"]
        age_options = ["All"] + sorted(first_df["age_group"].dropna().unique()) if 'age_group' in first_df.columns else ["All"]
        nccs_options = ["All"] + sorted(first_df["nccs_group"].dropna().unique()) if 'nccs_group' in first_df.columns else ["All"]
        gender_filter = st.sidebar.selectbox("Select Gender", gender_options)
        age_filter = st.sidebar.selectbox("Select Age Group", age_options)
        nccs_filter = st.sidebar.selectbox("Select NCCS Group", nccs_options)
        
        filtered_dataframes = {}
        for wave_key, df in loaded_dataframes.items():
            if df is not None:
                filtered_df = df.copy()
                if gender_filter != "All" and 'gender' in filtered_df.columns: filtered_df = filtered_df[filtered_df["gender"] == gender_filter]
                if age_filter != "All" and 'age_group' in filtered_df.columns: filtered_df = filtered_df[filtered_df["age_group"] == age_filter]
                if nccs_filter != "All" and 'nccs_group' in filtered_df.columns: filtered_df = filtered_df[filtered_df["nccs_group"] == nccs_filter]
                filtered_dataframes[wave_key] = filtered_df
        
        st.title("📰 Newspaper Analysis Dashboard")
        st.markdown(f"**City:** {selected_city} | **Filters:** Gender={gender_filter}, Age Group={age_filter}, NCCS={nccs_filter}")
        st.markdown("---")

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["NPS", "TOM", "Imagery", "Segmented NPS", "Sectional NPS"])
        
        with tab1:
            for wave_key, wave_df in filtered_dataframes.items():
                display_styled_dataframe(f"Wave: {wave_key}", dynamic_nps_analysis(wave_df, ref_col_name="q7_3"), wave_df, 'Paper', wave_key, drive_service)
        with tab2:
            for wave_key, wave_df in filtered_dataframes.items():
                display_styled_dataframe(f"Wave: {wave_key}", compute_tom_from_q5a(wave_df, ref_brand='3'), wave_df, 'Brand', wave_key, drive_service)
        with tab3:
            st.header("Brand Imagery Comparison")
            brand_linked = ['q6a.1', 'q6a.2', 'q6a.3', 'q6a.4', 'q6a.11', 'q6a.12', 'q6a.15', 'q6a.18']
            product_linked = ['q6a.5', 'q6a.6', 'q6a.7', 'q6a.8', 'q6a.9', 'q6a.10', 'q6a.13', 'q6a.14', 'q6a.16', 'q6a.17']
            for wave_key, wave_df in filtered_dataframes.items():
                st.subheader(f"Results for Wave: {wave_key}")
                base_counts = {col: wave_df[col].notna().sum() for col in wave_df.columns if str(col).startswith("q7_")}
                full_imagery_df = compute_dynamic_imagery(wave_df, base_counts, ref_col_name="q7_3")
                if not full_imagery_df.empty:
                    display_styled_dataframe("Brand Linked Imagery", full_imagery_df[full_imagery_df['Question'].isin(brand_linked)], wave_df, 'Question', wave_key, drive_service)
                    display_styled_dataframe("Product Linked Imagery", full_imagery_df[full_imagery_df['Question'].isin(product_linked)], wave_df, 'Question', wave_key, drive_service)
        with tab4:
            st.header("NPS by Segment Comparison")
            for wave_key, wave_df in filtered_dataframes.items():
                st.subheader(f"Analysis for Wave: {wave_key}")
                segment_cols = [col for col in ["gender", "age_group", "nccs_group"] if col in wave_df.columns]
                if segment_cols:
                    segment_col = st.selectbox("Segment NPS by", segment_cols, key=f"segment_{wave_key}")
                    if segment_col:
                        display_styled_dataframe("NPS by Segment", calculate_segmented_nps_with_sig(wave_df, segment_col), wave_df, 'Segment', wave_key, drive_service)
        with tab5:
            st.header("NPS by Section Comparison")
            for wave_key, wave_df in filtered_dataframes.items():
                display_styled_dataframe(f"Wave: {wave_key}", sectional_nps(wave_df, reference_brand="q12b_3"), wave_df, 'Q No.', wave_key, drive_service)

def login_page():
    st.title("Dashboard Login")
    with st.form("login_form"):
        username, password = st.text_input("Username"), st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if username == st.secrets["credentials"]["username"] and password == st.secrets["credentials"]["password"]:
                st.session_state.authenticated = True; st.rerun()
            else: st.error("Incorrect username or password.")
    st.write("---")
    try:
        col1, col2 = st.columns(2)
        col1.image("assets/logo1.png", width=200)
        col2.image("assets/logo2.png", width=200)
    except Exception: st.warning("Could not find logo images.")

if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if st.session_state.authenticated: main_dashboard()
else: login_page()