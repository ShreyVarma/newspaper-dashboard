# utils_V2_new.py

import pandas as pd
import numpy as np
import math
import re
import streamlit as st
Z_SCORE_95_CONFIDENCE = 1.96

def calculate_se_and_z_excel_style(p1, p2, n1, n2):
    term1 = (p1 * (100 - p1)) / n1 if n1 > 0 else 0
    term2 = (p2 * (100 - p2)) / n2 if n2 > 0 else 0
    se_squared = term1 + term2
    se = math.sqrt(se_squared) if se_squared > 0 else 0
    z = (p1 - p2) / se if se != 0 else None
    significance = "Significant" if z is not None and abs(z) > Z_SCORE_95_CONFIDENCE else "Not Significant"
    rounded_z = round(z, 2) if z is not None else None
    return round(se, 2), rounded_z, significance

def _add_comparison_and_sig_tests(scores_df, base_counts_df, ref_col, score_col_name, index_col_name):
    scores_df = scores_df.set_index(index_col_name)
    base_counts_df = base_counts_df.set_index(index_col_name)
    comparison_cols = [c for c in scores_df.columns if c != ref_col]
    for comp_col in comparison_cols:
        diff_results, z_scores, sig_results = [], [], []
        for idx, row in scores_df.iterrows():
            p1, p2 = row.get(ref_col), row.get(comp_col)
            n1, n2 = base_counts_df.loc[idx].get(ref_col, 0), base_counts_df.loc[idx].get(comp_col, 0)
            if n1 < 45 or n2 < 45 or pd.isna(n1) or pd.isna(n2):
                diff_results.append("LB"); z_scores.append(np.nan); sig_results.append("LB")
            elif pd.notna(p1) and pd.notna(p2) and n1 > 0 and n2 > 0:
                diff = p1 - p2
                _, z, sig = calculate_se_and_z_excel_style(p1, p2, n1, n2)
                diff_results.append(round(diff,2)); z_scores.append(z); sig_results.append(sig)
            else:
                diff_results.append("Insufficient base"); z_scores.append(np.nan); sig_results.append("Insufficient base")
        scores_df[f'{ref_col}_minus_{comp_col}'] = diff_results
        scores_df[f'Z_{ref_col}_vs_{comp_col}'] = z_scores
        scores_df[f'Sig_{ref_col}_vs_{comp_col}'] = sig_results
    return scores_df.reset_index()

@st.cache_data
def dynamic_nps_analysis(df, ref_col_name="q7_3"):
    df.columns = [str(c).lower() for c in df.columns]
    q7_cols = [col for col in df.columns if col.startswith("q7_")]
    q_ref = next((col for col in q7_cols if col == ref_col_name.lower()), None)
    if q_ref is None: raise ValueError(f"Reference column '{ref_col_name}' not found.")
    nps_results = {}
    for col in q7_cols:
        series = pd.to_numeric(df[col], errors='coerce').dropna()
        if not series.empty:
            freq = series.value_counts().reindex(range(11), fill_value=0)
            promoters = freq[9] + freq[10]
            detractors = freq.loc[0:6].sum()
            nps_results[col] = round((promoters - detractors) / len(series) * 100)
        else: nps_results[col] = None
    scores_df = pd.DataFrame([nps_results])
    scores_df['Paper'] = 'Overall'
    base_counts = df[q7_cols].notna().sum().to_frame().T
    base_counts['Paper'] = 'Overall'
    return _add_comparison_and_sig_tests(scores_df, base_counts, q_ref, 'nps', 'Paper')

@st.cache_data
def compute_tom_from_q5a(df, ref_brand):
    # This function remains the same, assuming it works correctly
    target_col = None
    for col in df.columns:
        if str(col).lower() in ['q5a_1', 'q5a_brand1']: target_col = col; break
    if target_col is None: raise ValueError("Could not find a TOM column like 'q5a_1' or 'q5a_brand1'.")
    q5_series = df[target_col].dropna().astype(int)
    counts = q5_series.value_counts()
    total = len(q5_series)
    if total == 0: return pd.DataFrame()
    tom_scores = {str(k): round((v / total) * 100) for k, v in counts.items()}
    tom_df = pd.DataFrame(list(tom_scores.items()), columns=['Brand', 'TOM (%)'])
    scores = tom_df.set_index('Brand')['TOM (%)']
    ref = str(ref_brand)
    if ref not in scores.index:
        st.warning(f"Reference brand '{ref}' not found for TOM analysis.")
        return pd.DataFrame()
    diff_rows = [{'Brand': f'{ref} - {brand}', 'TOM (%)': scores[ref] - scores[brand]} for brand in scores.index if brand != ref]
    if diff_rows: tom_df = pd.concat([tom_df, pd.DataFrame(diff_rows)], ignore_index=True)
    base = total
    score_lookup = tom_df.set_index("Brand")["TOM (%)"].to_dict()
    z_scores, significance = [], []
    for idx, row in tom_df.iterrows():
        brand_name = row["Brand"]
        if " - " in brand_name:
            b1, b2 = brand_name.split(" - ")
            p1, p2 = score_lookup.get(b1.strip()), score_lookup.get(b2.strip())
            if base < 45 or pd.isna(base):
                z_scores.append(np.nan); significance.append("LB")
            elif p1 is not None and p2 is not None:
                _, z, sig = calculate_se_and_z_excel_style(p1, p2, base, base)
                z_scores.append(z); significance.append(sig)
            else:
                z_scores.append(np.nan); significance.append("Insufficient base")
        else:
            z_scores.append(np.nan); significance.append(None)
    tom_df["Z Score"] = z_scores; tom_df["Significance"] = significance
    return tom_df

@st.cache_data
def calculate_segmented_nps_with_sig(df, segment_col):
    df.columns = [str(c).lower() for c in df.columns]
    segment_col = segment_col.lower()
    q7_cols = [col for col in df.columns if col.startswith('q7_')]
    q_ref = next((col for col in q7_cols if col == 'q7_3'), None)
    if q_ref is None: raise ValueError("Reference column 'q7_3' must be present.")
    results = []
    for segment in df[segment_col].dropna().unique():
        row = {'Segment': segment}
        segment_df = df[df[segment_col] == segment]
        for col in q7_cols:
            ratings = segment_df[col].dropna()
            total = ratings.count()
            if total == 0: row[col] = None
            else:
                freq_counts = ratings.value_counts().reindex(range(11), fill_value=0)
                promoters = freq_counts[9] + freq_counts[10]
                detractors = freq_counts.loc[0:6].sum()
                row[col] = round((promoters - detractors) / total * 100)
        for col in q7_cols:
            if col == q_ref: continue
            p1, p2 = row.get(q_ref), row.get(col)
            n1, n2 = segment_df[q_ref].notna().sum(), segment_df[col].notna().sum()
            if n1 < 45 or n2 < 45 or pd.isna(n1) or pd.isna(n2):
                row[f'{q_ref}_minus_{col}'] = "LB"; row[f'Z_{q_ref}_vs_{col}'] = np.nan; row[f'Sig_{q_ref}_vs_{col}'] = "LB"
            elif n1 == 0 or n2 == 0 or p1 is None or p2 is None:
                row[f'{q_ref}_minus_{col}'] = "Insufficient base"; row[f'Z_{q_ref}_vs_{col}'] = np.nan; row[f'Sig_{q_ref}_vs_{col}'] = "Insufficient base"
            else:
                diff = p1 - p2
                _, z, sig = calculate_se_and_z_excel_style(p1, p2, n1, n2)
                row[f'{q_ref}_minus_{col}'] = round(diff,2); row[f'Z_{q_ref}_vs_{col}'] = z; row[f'Sig_{q_ref}_vs_{col}'] = sig
        results.append(row)
    return pd.DataFrame(results)

@st.cache_data
def compute_dynamic_imagery(df, base_counts, ref_col_name="q7_3"):
    df.columns = [str(c).lower() for c in df.columns]
    ref_col_name = ref_col_name.lower()
    q7_cols = [col for col in df.columns if col.startswith("q7_")]
    q_ref = next((col for col in q7_cols if col == ref_col_name), None)
    if q_ref is None: raise ValueError(f"Reference column '{ref_col_name}' not found.")
    q6_pattern = re.compile(r"^(q6a)[._/](\d+)[._/](\d+)$")
    q6_lookup = {}
    question_numbers = set()
    for col in df.columns:
        match = q6_pattern.match(col)
        if match:
            q_num, b_num = match.group(2), match.group(3)
            if int(q_num) <= 18:
                q6_lookup[(q_num, b_num)] = col
                question_numbers.add(q_num)
    results = []
    for q_num in sorted(list(question_numbers)):
        row = {'Question': f'q6a.{q_num}'}
        for q7_col in q7_cols:
            brand_num_match = re.search(r'_(\d+)', q7_col)
            if not brand_num_match: continue
            brand_num = brand_num_match.group(1)
            q6_col = q6_lookup.get((q_num, brand_num))
            brand_rows = df[df[q7_col].notna()]
            if q6_col and q6_col in brand_rows.columns and not brand_rows.empty:
                score = (brand_rows[q6_col] >= 1).sum() / len(brand_rows) * 100
                row[q7_col] = round(score)
            else: row[q7_col] = np.nan
        results.append(row)
    imagery_df = pd.DataFrame(results)
    for q7_col in q7_cols:
        if q7_col != q_ref:
            z_scores, sig_results, diff_results = [], [], []
            n1, n2 = base_counts.get(q_ref, 0), base_counts.get(q7_col, 0)
            for _, row in imagery_df.iterrows():
                p1, p2 = row.get(q_ref), row.get(q7_col)
                if n1 < 45 or n2 < 45 or pd.isna(n1) or pd.isna(n2):
                    diff_results.append("LB"); z_scores.append(np.nan); sig_results.append("LB")
                elif n1 > 0 and n2 > 0 and pd.notna(p1) and pd.notna(p2):
                    diff = p1 - p2
                    _, z, sig = calculate_se_and_z_excel_style(p1, p2, n1, n2)
                    diff_results.append(round(diff,2)); z_scores.append(z); sig_results.append(sig)
                else:
                    diff_results.append(np.nan); z_scores.append(np.nan); sig_results.append("Insufficient base")
            imagery_df[f'{q_ref}_minus_{q7_col}'] = diff_results
            imagery_df[f'Z_{q_ref}_vs_{q7_col}'] = z_scores
            imagery_df[f'Sig_{q_ref}_vs_{q7_col}'] = sig_results
    return imagery_df

@st.cache_data
def sectional_nps(df, reference_brand="q12b_3", max_q_num=10):
    df.columns = [str(c).lower() for c in df.columns]
    reference_brand = reference_brand.lower()
    q12b_pattern = re.compile(r"^q12b[._/](\d+)[._/](\d+)")
    results_list = []
    for col in df.columns:
        match = q12b_pattern.match(col)
        if match:
            brand_num, section_num = match.group(1), int(match.group(2))
            if section_num <= max_q_num:
                series = pd.to_numeric(df[col], errors='coerce').dropna()
                if not series.empty:
                    freq = series.value_counts().reindex(range(11), fill_value=0)
                    promoters = freq[9] + freq[10]
                    detractors = freq.loc[0:6].sum()
                    nps = round((promoters - detractors) / len(series) * 100)
                    results_list.append({'section': section_num, 'brand_col_name': f'q12b_{brand_num}', 'nps': nps, 'base': len(series)})
    if not results_list: return pd.DataFrame()
    temp_df = pd.DataFrame(results_list)
    nps_df = temp_df.pivot_table(index='section', columns='brand_col_name', values='nps').reset_index()
    base_df = temp_df.pivot_table(index='section', columns='brand_col_name', values='base').reset_index()
    nps_df.rename(columns={'section': 'Q No.'}, inplace=True)
    base_df.rename(columns={'section': 'Q No.'}, inplace=True)
    return _add_comparison_and_sig_tests(nps_df, base_df, reference_brand, 'nps', 'Q No.')