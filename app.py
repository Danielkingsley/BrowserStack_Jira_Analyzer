import io
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


# ── helpers ───────────────────────────────────────────────────────────
def build_raw_df(results: list[dict]) -> pd.DataFrame:
    """Group results by Jira ID → one row per Jira ID with deduplicated TCs."""
    rows = {}
    for r in results:
        jid = r["jira_id"]
        rows.setdefault(jid, {})[r["identifier"]] = r["test_case_name"]
    return pd.DataFrame([
        {"Jira ID": jid, "Test Case Count": len(tcs), "Test Cases": ", ".join(sorted(tcs))}
        for jid, tcs in sorted(rows.items())
    ])


def show_df(df: pd.DataFrame):
    st.dataframe(
        df, width="stretch", hide_index=True,
        column_config={"Test Case Count": st.column_config.NumberColumn("Test Case Count", alignment="center")},
    )


def cache_age_str(ts: str) -> str:
    fetched_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc)
    days, hours, mins = delta.days, delta.seconds // 3600, (delta.seconds % 3600) // 60
    if days:   return f"{days} day{'s' if days > 1 else ''} ago"
    if hours:  return f"{hours} hour{'s' if hours > 1 else ''} ago"
    return f"{mins} minute{'s' if mins > 1 else ''} ago"


# ── How to Use dialog ─────────────────────────────────────────────────
@st.dialog("📖 How to Use", width="large")
def show_help():
    st.markdown("""
### Overview
This dashboard connects **BrowserStack Test Management** with **Jira** to show you which
Jira issues have linked test cases and which ones don't.

---

### Step 1 — Project ID
Enter your BrowserStack project ID in the **Project ID** field.
This is the numeric ID of your BrowserStack Test Management project (e.g. `22` maps to project `PR-22`).

---

### Step 2 — JQL Query or Filter ID
Enter a **Jira Query Language (JQL)** expression or a saved **Filter ID** to define which Jira issues to compare against.

| Type | Example |
|---|---|
| Open sprint | `project = PP AND sprint in openSprints()` |
| Issue type | `project = PP AND issuetype = Story` |
| Specific sprint | `project = PP AND sprint = "Sprint 42"` |
| Multiple types | `project = PP AND issuetype in (Story, Bug)` |
| Saved filter | `filter = 12345` |

> **Tip:** You can copy a filter ID from Jira → Filters → View all filters → click your filter → the number in the URL is the filter ID.

---

### Step 3 — Use Cache
The **Use Cache** checkbox controls whether BrowserStack data is loaded from Supabase cache or fetched fresh from the API.

| Setting | Behaviour |
|---|---|
| ✅ Checked (default) | Loads previously cached BrowserStack test cases instantly |
| ❌ Unchecked | Fetches live data from BrowserStack API (slower, up to date) |

The cache info card below the controls shows **when** the data was last fetched and **how old** it is.
Uncheck and re-run whenever you've added or updated test cases in BrowserStack.

---

### Step 4 — Run Analysis
Click **▶ Run Analysis** to:
1. Load BrowserStack test cases (from cache or API)
2. Fetch Jira issues matching your JQL query
3. Compare them and display results

---

### Reading the Dashboard

**BrowserStack KPIs (top row)**
| Metric | Meaning |
|---|---|
| Total Test Cases | All unique test cases in the BrowserStack project |
| Mapped to Jira | Test cases that have at least one Jira issue linked |
| Unmapped | Test cases with no Jira link at all |
| Unique Jira IDs | Number of distinct Jira tickets referenced across all test cases |
| Mapping % | Percentage of test cases that are mapped to Jira |

**Jira Comparison table**
| Column | Meaning |
|---|---|
| Jira ID | The Jira issue key (e.g. `PP-123`) |
| Status | ✅ Mapped = has test cases, ❌ Not Mapped = no test cases |
| Test Case Count | How many BrowserStack test cases are linked to this Jira issue |
| Test Cases | Comma-separated list of BrowserStack test case IDs |

Use the **All / ✅ Mapped / ❌ Not Mapped** filter to narrow the view.

**All Jira Mapped BrowserStack Test Cases (expandable)**
Shows all Jira-linked test cases grouped by Jira ID — regardless of your JQL query.
Useful for a full audit of what's mapped in BrowserStack.

---

### Downloading Data
Click **⬇ Download Excel** to export:
- **Sheet 1 — Jira Comparison:** the full comparison table
- **Sheet 2 — All BS Mapped Test Cases:** all BrowserStack test case ↔ Jira mappings grouped by Jira ID
    """)


# ── title row ─────────────────────────────────────────────────────────
title_col, help_col = st.columns([9, 1])
with title_col:
    st.title("BrowserStack – Jira Mapping Dashboard")
with help_col:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    st.markdown("&nbsp;", unsafe_allow_html=True)
    if st.button("📖 How to Use", use_container_width=True):
        show_help()

# ── controls ──────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns([1, 3, 1, 1, 1])
with col1:
    project_id = st.number_input("Project ID", value=22, step=1)
with col2:
    jql_query = st.text_input("JQL Query or Filter ID",
                              placeholder="e.g. project = PP AND sprint in openSprints()")
with col3:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    use_jql   = st.checkbox("Enable JQL", value=True)
with col4:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    use_cache = st.checkbox("Use Cache", value=True)
with col4:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    run = st.button("▶  Run Analysis", use_container_width=True, type="primary")

st.divider()

# ── session state ─────────────────────────────────────────────────────
for key in ("stats", "df_cmp", "jira_list", "results", "unmapped_cases", "cache_ts"):
    if key not in st.session_state:
        st.session_state[key] = None

if run:
    if not jql_query.strip():
        st.warning("Enable JQL is checked but no query was provided. Stopping...")
        st.stop()

    analyzer  = BrowserStackJiraAnalyzer()
    bs_status = st.empty()

    analyzer.get_all_test_cases_from_project(
        int(project_id), use_cache=use_cache,
        on_progress=lambda p, t: bs_status.info(f"Fetching BrowserStack test cases… page {p} / {t}")
    )
    mapped_unique = len(set(r["identifier"] for r in analyzer.results))
    bs_status.success(f"✅ BrowserStack test cases loaded ({analyzer.total_test_cases} total, {mapped_unique} mapped)")

    jira_list = []
    if use_jql:
        with st.spinner("Fetching Jira issues…"):
            try:
                jira_list = analyzer.get_jira_issues_from_query(analyzer.get_jira_client(), jql_query)
            except Exception as e:
                st.error(f"Jira connection failed: {e}")
    else:
        st.warning("⚠️ JQL query is disabled. Running full BrowserStack analysis only — no Jira comparison will be shown.")

    st.session_state.stats         = analyzer.get_stats()
    st.session_state.df_cmp        = analyzer.compare_with_jira_query(jira_list)
    st.session_state.jira_list     = jira_list
    st.session_state.results       = analyzer.results
    st.session_state.unmapped_cases = analyzer.unmapped_cases
    st.session_state.cache_ts      = analyzer.cache_timestamp

# ── render ────────────────────────────────────────────────────────────
if st.session_state.stats is None:
    st.info("Enter your JQL query above and click **Run Analysis** to begin.")
    st.stop()

stats     = st.session_state.stats
df_cmp    = st.session_state.df_cmp
jira_list = st.session_state.jira_list
results   = st.session_state.results
unmapped_cases = st.session_state.unmapped_cases
cache_ts  = st.session_state.cache_ts

# ── cache info card ───────────────────────────────────────────────────
if cache_ts:
    try:
        friendly_date = datetime.fromisoformat(cache_ts.replace("Z", "+00:00")).strftime("%b %d, %Y at %I:%M %p UTC")
        st.info(f"📦 **Showing cached data** — fetched on **{friendly_date}** ({cache_age_str(cache_ts)}). "
                f"Uncheck **Use Cache** and re-run to fetch fresh data.")
    except Exception:
        st.info("📦 Showing cached data. Uncheck **Use Cache** and re-run to fetch fresh data.")
else:
    st.info("🔄 Showing live data fetched just now.")

# ── BrowserStack KPIs ─────────────────────────────────────────────────
st.subheader("Overall Comparison")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Test Cases",       stats["Total Test Cases"])
c2.metric("Total TC Mapped to Jira", stats["Mapped to Jira"])
c3.metric("Total Unmapped",          stats["Unmapped"])
c4.metric("Unique Jira IDs",         stats["Unique Jira IDs"])
c5.metric("Mapping %",               f"{stats['Mapping %']}%")

st.divider()

# ── Jira Comparison ───────────────────────────────────────────────────
jira_col1, jira_col2, jira_col3 = st.columns([4, 1, 2])
with jira_col1:
    st.subheader("Jira Comparison")
# with jira_col2:
#    show_jira = st.checkbox("Show Jira Comparison", value=True)

# if show_jira:
if not jira_list:
    st.info("No Jira issues returned – check your JQL query or credentials.")
else:
    col_t, col_u, col_m = st.columns(3)
    col_t.metric("Total Jira Issues in Query",   len(jira_list))
    col_m.metric("Jira Mapped to Test Case",     (df_cmp["Status"] == "✅ Mapped").sum())
    col_u.metric("Jira NOT Mapped to Test Case", (df_cmp["Status"] == "❌ Not Mapped").sum())

    filter_opt = st.radio("Show", ["All", "✅ Mapped", "❌ Not Mapped"],
                          horizontal=True, label_visibility="collapsed")
    show_df(df_cmp if filter_opt == "All" else df_cmp[df_cmp["Status"] == filter_opt])

    # Excel export
    df_raw     = build_raw_df(results)
    df_unmapped = pd.DataFrame(unmapped_cases or [], columns=["identifier", "test_case_name"])\
                    .rename(columns={"identifier": "Test Case ID", "test_case_name": "Test Case Name"})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_cmp.to_excel(writer, sheet_name="Jira Comparison", index=False)
        df_raw.to_excel(writer, sheet_name="All BS Mapped Test Cases", index=False)
        df_unmapped.to_excel(writer, sheet_name="Unmapped Test Cases", index=False)
    st.download_button("⬇ Download Excel", data=buf.getvalue(),
                       file_name="jira_bs_comparison.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.divider()

# ── All Jira Mapped BrowserStack Test Cases ───────────────────────────
with st.expander(f"All Jira Mapped BrowserStack Test Cases — {stats['Unique Jira IDs']}"):
    if results:
        show_df(build_raw_df(results))
