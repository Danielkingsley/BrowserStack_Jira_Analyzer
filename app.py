import io
from collections import defaultdict
from datetime import datetime, timezone
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
for key in ("stats", "df_cmp", "jira_list", "results", "cache_ts"):
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
    mapped_unique = len(set(r["identifier"] for r in analyzer.results))
    bs_status.success(f"✅ BrowserStack test cases loaded ({analyzer.total_test_cases} total, {mapped_unique} mapped)")

    with st.spinner("Fetching Jira issues…"):
        try:
            jira_client = analyzer.get_jira_client()
            jira_list   = analyzer.get_jira_issues_from_query(jira_client, jql_query)
        except Exception as e:
            st.error(f"Jira connection failed: {e}")
            jira_list = []

    st.session_state.stats    = analyzer.get_stats()
    st.session_state.df_cmp   = analyzer.compare_with_jira_query(jira_list)
    st.session_state.jira_list = jira_list
    st.session_state.results  = analyzer.results
    st.session_state.cache_ts = analyzer.cache_timestamp

# ── render ───────────────────────────────────────────────────────────
if st.session_state.stats is None:
    st.info("Enter your JQL query above and click **Run Analysis** to begin.")
    st.stop()

stats     = st.session_state.stats
df_cmp    = st.session_state.df_cmp
jira_list = st.session_state.jira_list
results   = st.session_state.results
cache_ts  = st.session_state.cache_ts

# ── cache info card ───────────────────────────────────────────────────
if cache_ts:
    try:
        fetched_at = datetime.fromisoformat(cache_ts.replace("Z", "+00:00"))
        now        = datetime.now(timezone.utc)
        delta      = now - fetched_at.astimezone(timezone.utc)
        days       = delta.days
        hours      = delta.seconds // 3600
        mins       = (delta.seconds % 3600) // 60

        if days > 0:
            age_str = f"{days} day{'s' if days > 1 else ''} ago"
        elif hours > 0:
            age_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            age_str = f"{mins} minute{'s' if mins > 1 else ''} ago"

        friendly_date = fetched_at.strftime("%b %d, %Y at %I:%M %p UTC")
        st.info(f"📦 **Showing cached data** — fetched on **{friendly_date}** ({age_str}). "
                f"Uncheck **Use Cache** and re-run to fetch fresh data.")
    except Exception:
        st.info("📦 Showing cached data. Uncheck **Use Cache** and re-run to fetch fresh data.")
else:
    st.success("🔄 Showing live data fetched just now.")

# ── BrowserStack KPIs ────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Test Cases", stats["Total Test Cases"])
c2.metric("Mapped to Jira",   stats["Mapped to Jira"])
c3.metric("Unmapped",         stats["Unmapped"])
c4.metric("Unique Jira IDs",  stats["Unique Jira IDs"])
c5.metric("Mapping %",        f"{stats['Mapping %']}%")

st.divider()

# ── Jira Comparison ──────────────────────────────────────────────────
# header row with title + info popover + JQL toggle
jira_col1, jira_col2, jira_col3 = st.columns([4, 1, 2])
with jira_col1:
    st.subheader("Jira Comparison")
with jira_col2:
    with st.popover("ℹ️ Help"):
        st.markdown("""
**JQL Query** — Enter a Jira Query Language expression to fetch issues.

**Examples:**
- `project = PP AND sprint in openSprints()`
- `project = PP AND issuetype = Story`
- `filter = 12345` *(use a saved filter ID)*

**Toggle** — Use the checkbox to show/hide the Jira Comparison section without re-running.

The table compares your Jira issues against BrowserStack test cases:
- ✅ **Mapped** — Jira issue has at least one linked test case
- ❌ **Not Mapped** — Jira issue has no test cases in BrowserStack
        """)
with jira_col3:
    show_jira = st.checkbox("Show Jira Comparison", value=True)

if show_jira:
    if not jira_list:
        st.info("No Jira issues returned – check your JQL query or credentials.")
    else:
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

        # Excel download
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

st.divider()

# ── Raw BrowserStack Test Cases ───────────────────────────────────────
with st.expander("Raw BrowserStack Test Cases"):
    if results:
        bs_ids = sorted(set(r["jira_id"] for r in results))
        raw_rows = []
        for jira_id in bs_ids:
            seen = {}
            for r in results:
                if r["jira_id"] == jira_id:
                    seen[r["identifier"]] = r["test_case_name"]
            raw_rows.append({
                "Jira ID":         jira_id,
                "Test Case Count": len(seen),
                "Test Cases":      ", ".join(sorted(seen.keys())),
            })
        st.dataframe(pd.DataFrame(raw_rows), width='stretch', column_config={"Test Case Count": st.column_config.NumberColumn("Test Case Count", alignment="center")}, hide_index=True)
