import io
import streamlit as st
import pandas as pd
from BrowserStackJiraAnalyzer import BrowserStackJiraAnalyzer

st.set_page_config(
    page_title="BrowserStack – Jira Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding: 1rem 2rem 1rem;}
    section[data-testid="stSidebar"] {min-width: 280px; max-width: 320px;}
</style>
""", unsafe_allow_html=True)

# ── sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    project_id = st.number_input("BrowserStack Project ID", value=22, step=1)
    use_cache  = st.checkbox("Use Supabase Cache", value=True)
    jql_query  = st.text_input("JQL Query or Filter ID",
                               placeholder="e.g. project = PP AND sprint in openSprints()")
    run = st.button("▶  Run Analysis", use_container_width=True, type="primary")
    st.divider()
    st.caption("Credentials are read from Streamlit Secrets.")

# ── main ─────────────────────────────────────────────────────────────
st.title("BrowserStack – Jira Mapping Dashboard")

if not run:
    st.info("👈 Enter your JQL query in the sidebar and click **Run Analysis** to begin.")
    st.stop()

if not jql_query.strip():
    st.warning("Please enter a JQL query or Filter ID.")
    st.stop()

analyzer = BrowserStackJiraAnalyzer()

with st.spinner("Fetching BrowserStack test cases…"):
    analyzer.get_all_test_cases_from_project(int(project_id), use_cache=use_cache)

with st.spinner("Fetching Jira issues…"):
    try:
        jira_client = analyzer.get_jira_client()
        jira_list   = analyzer.get_jira_issues_from_query(jira_client, jql_query)
    except Exception as e:
        st.error(f"Jira connection failed: {e}")
        jira_list = []

# ── BrowserStack KPIs ────────────────────────────────────────────────
stats = analyzer.get_stats()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Test Cases", stats["Total Test Cases"])
c2.metric("Mapped to Jira",   stats["Mapped to Jira"])
c3.metric("Unmapped",         stats["Unmapped"])
c4.metric("Unique Jira IDs",  stats["Unique Jira IDs"])
c5.metric("Mapping %",        f"{stats['Mapping %']}%")

st.divider()

# ── Jira Comparison ──────────────────────────────────────────────────
st.subheader("Jira Comparison")

if not jira_list:
    st.info("No Jira issues returned – check your JQL query or credentials.")
    st.stop()

df_cmp = analyzer.compare_with_jira_query(jira_list)

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
st.dataframe(df_view, use_container_width=True, hide_index=True)

# ── Excel download ───────────────────────────────────────────────────
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    df_cmp.to_excel(writer, sheet_name="Jira Comparison", index=False)
    pd.DataFrame(analyzer.results).to_excel(writer, sheet_name="Raw Data", index=False)
st.download_button(
    "⬇ Download Excel",
    data=buf.getvalue(),
    file_name="jira_bs_comparison.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ── Raw data expander ────────────────────────────────────────────────
with st.expander("Raw BrowserStack Test Cases"):
    st.dataframe(pd.DataFrame(analyzer.results), use_container_width=True, hide_index=True)
