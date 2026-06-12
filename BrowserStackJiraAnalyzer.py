import json
import logging
import os
import requests
import pandas as pd
from jira import JIRA
from datetime import datetime
from collections import defaultdict
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _secret(key: str) -> str:
    """Read from st.secrets first, fall back to env var."""
    try:
        import streamlit as st
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, "")


JIRA_BASE_URL    = _secret("JIRA_BASE_URL")
JIRA_USERNAME    = _secret("JIRA_USERNAME")
JIRA_API_TOKEN   = _secret("JIRA_API_TOKEN")

BS_USERNAME      = _secret("BS_USERNAME")
BS_API_KEY       = _secret("BS_API_KEY")
BS_API_URL       = "https://test-management.browserstack.com/api/v2/projects/"

SUPABASE_URL     = _secret("SUPABASE_URL")
SUPABASE_KEY     = _secret("SUPABASE_SERVICE_KEY") or _secret("SUPABASE_KEY")
SUPABASE_TABLE   = "browserstack_cache"


def _supabase_client() -> Client | None:
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None


class BrowserStackJiraAnalyzer:

    def __init__(self):
        self.results: list[dict] = []
        self.total_test_cases: int = 0
        self.unmapped_cases: list[dict] = []
        self.unmapped_count: int = 0
        self.cache_timestamp: str | None = None
        self._supabase = _supabase_client()

    # ------------------------------------------------------------------
    # Supabase cache helpers
    # ------------------------------------------------------------------
    def save_to_cache(self, project_id: int, data: dict):
        if not self._supabase:
            return
        try:
            payload = {
                "project_id": project_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": json.dumps(data),
            }
            self._supabase.table(SUPABASE_TABLE).upsert(payload, on_conflict="project_id").execute()
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def load_from_cache(self, project_id: int) -> tuple[dict | None, str | None]:
        if not self._supabase:
            return None, None
        try:
            response = (
                self._supabase.table(SUPABASE_TABLE)
                .select("*")
                .eq("project_id", project_id)
                .execute()
            )
            if response.data:
                row = response.data[0]
                logger.info(f"Loaded cache (saved: {row['timestamp']})")
                return json.loads(row["data"]), row['timestamp']
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
        return None, None

    # ------------------------------------------------------------------
    # BrowserStack
    # ------------------------------------------------------------------
    def _get(self, url: str):
        return requests.get(url, auth=(BS_USERNAME, BS_API_KEY))

    def get_all_test_cases_from_project(self, project_id: int, use_cache: bool = True,
                                        on_progress=None):
        """Fetch all test cases. on_progress(page, total_pages) called each page."""
        if use_cache:
            cached, ts = self.load_from_cache(project_id)
            if cached:
                self.results = cached.get("results", [])
                self.unmapped_cases = cached.get("unmapped_cases", [])
                self.total_test_cases = cached.get("total_test_cases", 0)
                self.unmapped_count = cached.get("unmapped_count", 0)
                self.cache_timestamp = ts
                return self.results

        PAGE_SIZE = 300
        url = f"{BS_API_URL}PR-{project_id}/test-cases"
        data = self._get(f"{url}?page_size={PAGE_SIZE}").json()
        total_count = data["info"]["count"]
        total_pages = int(total_count / PAGE_SIZE) + (1 if total_count % PAGE_SIZE else 0)

        results, unmapped_cases = [], []
        unique_identifiers = set()

        for page in range(1, total_pages + 1):
            if on_progress:
                on_progress(page, total_pages)
            page_data = self._get(f"{url}?page_size={PAGE_SIZE}&p={page}").json()
            for tc in page_data.get("test_cases", []):
                identifier = tc.get("identifier", "N/A")
                title = tc.get("title", "N/A")
                unique_identifiers.add(identifier)
                if tc.get("issues"):
                    for issue in tc["issues"]:
                        jira_id = issue.get("jira_id")
                        if jira_id:
                            results.append({
                                "identifier": identifier,
                                "test_case_name": title,
                                "jira_id": jira_id,
                                "issue_type": issue.get("issue_type"),
                            })
                else:
                    unmapped_cases.append({"identifier": identifier, "test_case_name": title})

        self.results = results
        self.unmapped_cases = unmapped_cases
        # total = all unique test cases seen (mapped + unmapped)
        self.total_test_cases = len(unique_identifiers)
        self.unmapped_count = len(unmapped_cases)
        self.cache_timestamp = None  # fresh fetch          

        self.save_to_cache(project_id, {
            "results": results,
            "unmapped_cases": unmapped_cases,
            "total_test_cases": self.total_test_cases,
            "unmapped_count": self.unmapped_count,
        })
        return results

    # ------------------------------------------------------------------
    # Jira
    # ------------------------------------------------------------------
    def get_jira_client(self) -> JIRA:
        return JIRA(server=JIRA_BASE_URL, basic_auth=(JIRA_USERNAME, JIRA_API_TOKEN))

    def get_jira_issues_from_query(self, jira: JIRA, jql_query: str) -> list[str]:
        try:
            try:
                final_jql = jira.filter(jql_query).jql
            except Exception:
                final_jql = jql_query
            issues = jira.search_issues(final_jql, maxResults=False)
            return [i.key for i in issues]
        except Exception as e:
            logger.error(f"Failed to fetch Jira issues: {e}")
            return []

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------
    def analyze_jira_mapping(self) -> dict:
        mapping = defaultdict(list)
        for item in self.results:
            mapping[item["jira_id"]].append({
                "identifier": item["identifier"],
                "test_case_name": item["test_case_name"],
            })
        return dict(mapping)

    def compare_with_jira_query(self, jira_query_list: list[str]) -> pd.DataFrame:
        bs_ids = set(item["jira_id"] for item in self.results)
        jira_ids = set(jira_query_list)

        rows = []
        for jira_id in sorted(bs_ids & jira_ids):
            tcs = [i["identifier"] for i in self.results if i["jira_id"] == jira_id]
            rows.append({
                "Jira ID": jira_id,
                "Status": "✅ Mapped",
                "Test Case Count": len(tcs),
                "Test Cases": ", ".join(tcs),
            })
        for jira_id in sorted(jira_ids - bs_ids):
            rows.append({
                "Jira ID": jira_id,
                "Status": "❌ Not Mapped",
                "Test Case Count": 0,
                "Test Cases": "",
            })
        return pd.DataFrame(rows)

    def get_stats(self) -> dict:
        jira_mapping = self.analyze_jira_mapping()
        mapped_tcs = len(set(i["identifier"] for i in self.results))
        return {
            "Total Test Cases": self.total_test_cases,
            "Mapped to Jira": mapped_tcs,
            "Unmapped": self.unmapped_count,
            "Unique Jira IDs": len(jira_mapping),
            "Mapping %": round(mapped_tcs / self.total_test_cases * 100, 1) if self.total_test_cases else 0,
        }
