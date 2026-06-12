import io
from collections import defaultdict
import streamlit as st
import pandas as pd
from BrowserStackJiraAnalyzer import BrowserStackJiraAnalyzer

st.set_page_config(
    page_title="BrowserStack – Jira Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding: 1rem 2rem 1rem;}
    button[data-testid="collapsedControl"] {display: none;}
    button[data-testid="stNumberInputStepUp"],
    button[data-testid="stNumberInputStepDown"] {display: none;}
    /* center-align columns by header name */
    [data-testid="stDataFrameResizable"] th:nth-child(3),
    [data-testid="stDataFrameResizable"] td:nth-child(3) {text-align: center !important;}
</style>
""", unsafe_allow_html=True)

st.title("BrowserStack – Jira Mapping Dashboard")

# ── controls ─────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns([1, 3, 1, 1])
with col1:
    project_id = st.number_input("Project ID", value=22, step=1)
with col2:
    jql_query = st.text_input("JQL Query or Filter ID",
                              placeholder="e.g. project = PP AND sprint in openSprints()")
with col3:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    use_cache = st.checkbox("Use Cache", value=True)
with col4:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    run = st.button("▶  Run Analysis", use_container_width=True, type="primary")

st.divider()

# ── session state ────────────────────────────────────────────────────
for key in ("stats", "df_cmp", "jira_list", "results"):
    if key not in st.session_state:
        st.session_state[key] = None

if run:
    if not jql_query.strip():
        st.warning("Please enter a JQL query or Filter ID.")
        st.stop()

    analyzer = BrowserStackJiraAnalyzer()
    bs_status = st.empty()

    def on_progress(page, total):
        bs_status.info(f"Fetching BrowserStack test cases… page {page} / {total}")

    analyzer.get_all_test_cases_from_project(int(project_id),
                                             use_cache=use_cache,
                                             on_progress=on_progress)
    bs_status.success(f"✅ BrowserStack test cases loaded ({analyzer.total_test_cases} total, {len(set(r['identifier'] for r in analyzer.results))} mapped rows)")

    with st.spinner("Fetching Jira issues…"):
        try:
            jira_client = analyzer.get_jira_client()
            jira_list   = analyzer.get_jira_issues_from_query(jira_client, jql_query)
        except Exception as e:
            st.error(f"Jira connection failed: {e}")
            jira_list = []

    st.session_state.stats     = analyzer.get_stats()
    st.session_state.df_cmp    = analyzer.compare_with_jira_query(jira_list)
    st.session_state.jira_list = jira_list
    st.session_state.results   = analyzer.results

# ── render ───────────────────────────────────────────────────────────
if st.session_state.stats is None:
    st.info("Enter your JQL query above and click **Run Analysis** to begin.")
    st.stop()

stats     = st.session_state.stats
df_cmp    = st.session_state.df_cmp
jira_list = st.session_state.jira_list
results   = st.session_state.results

# ── BrowserStack KPIs ────────────────────────────────────────────────
st.subheader("Overall Comparison")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Test Cases", stats["Total Test Cases"])
c2.metric("Total TC Mapped to Jira",   stats["Mapped to Jira"])
c3.metric("Total Unmapped TC",         stats["Unmapped"])
c4.metric("Unique Jira IDs",  stats["Unique Jira IDs"])
c5.metric("Mapping %",        f"{stats['Mapping %']}%")

st.divider()

# ── Jira Comparison ──────────────────────────────────────────────────
st.subheader("Jira Comparison")

if not jira_list:
    st.info("No Jira issues returned – check your JQL query or credentials.")
    st.stop()

mapped_count   = (df_cmp["Status"] == "✅ Mapped").sum()
unmapped_count = (df_cmp["Status"] == "❌ Not Mapped").sum()

col_m, col_u, col_t = st.columns(3)
col_m.metric("Jira Mapped to Test Case",     mapped_count)
col_u.metric("Jira NOT Mapped to Test Case", unmapped_count)
col_t.metric("Total Jira Issues in Query",   len(jira_list))

filter_opt = st.radio(
    "Show", ["All", "✅ Mapped", "❌ Not Mapped"],
    horizontal=True, label_visibility="collapsed"
)
df_view = df_cmp if filter_opt == "All" else df_cmp[df_cmp["Status"] == filter_opt]
st.dataframe(df_view, width='stretch', column_config={"Test Case Count": st.column_config.NumberColumn("Test Case Count", alignment="center")}, hide_index=True)

# ── Excel download ───────────────────────────────────────────────────
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    df_cmp.to_excel(writer, sheet_name="Jira Comparison", index=False)
    pd.DataFrame(results).to_excel(writer, sheet_name="Raw Data", index=False)
st.download_button(
    "⬇ Download Excel",
    data=buf.getvalue(),
    file_name="jira_bs_comparison.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ── Raw BrowserStack Test Cases ───────────────────────────────────────
with st.expander("Raw BrowserStack Test Cases"):
    if results:
        bs_ids = sorted(set(r["jira_id"] for r in results))
        raw_rows = []
        for jira_id in bs_ids:
            tcs = [i for i in results if i["jira_id"] == jira_id]
            # deduplicate by identifier
            seen = {}
            for r in tcs:
                seen[r["identifier"]] = r["test_case_name"]
            raw_rows.append({
                "Jira ID":          jira_id,
                "Test Case Count":  len(seen),
                "Test Cases":       ", ".join(sorted(seen.keys())),
            })
        st.dataframe(pd.DataFrame(raw_rows), width='stretch', column_config={"Test Case Count": st.column_config.NumberColumn("Test Case Count", alignment="center")}, hide_index=True)
