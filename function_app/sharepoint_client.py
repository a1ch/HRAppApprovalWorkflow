"""
SharePoint client — reads new list items and writes approval state back.
Uses MSAL (Microsoft Authentication Library) with a service principal
(client credentials flow) so no user login is required.

Required App Settings (Azure Function App Configuration):
  SP_TENANT_ID        - Azure AD tenant ID
  SP_CLIENT_ID        - App registration client ID
  SP_CLIENT_SECRET    - App registration client secret
  SP_SITE_URL         - e.g. https://streamflogroup.sharepoint.com/hrcp/hrst
"""

import os
import logging
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from list_configs import ListConfig

import msal
import requests

logger = logging.getLogger(__name__)


class SharePointClient:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.tenant_id     = os.environ["SP_TENANT_ID"]
        self.client_id     = os.environ["SP_CLIENT_ID"]
        self.client_secret = os.environ["SP_CLIENT_SECRET"]
        self.site_url      = os.environ["SP_SITE_URL"].rstrip("/")
        self._token: Optional[str] = None
        self._site_id: Optional[str] = None
        self._list_id_cache: dict[str, str] = {}   # display_name -> list_id

    # ── Auth ──────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token:
            return self._token
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(f"MSAL auth failed: {result.get('error_description')}")
        self._token = result["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    # ── Site / List resolution ────────────────────────────────────────────

    def _get_site_id(self) -> str:
        if self._site_id:
            return self._site_id
        without_scheme = self.site_url.replace("https://", "")
        parts = without_scheme.split("/", 1)
        host  = parts[0]
        path  = parts[1] if len(parts) > 1 else ""
        url   = f"{self.GRAPH_BASE}/sites/{host}:/{path}"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        self._site_id = r.json()["id"]
        return self._site_id

    def _get_list_id(self, display_name: str) -> str:
        """Resolve a list display name to its Graph API list ID (cached)."""
        if display_name in self._list_id_cache:
            return self._list_id_cache[display_name]
        site_id = self._get_site_id()
        url = f"{self.GRAPH_BASE}/sites/{site_id}/lists"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        for lst in r.json().get("value", []):
            self._list_id_cache[lst["displayName"]] = lst["id"]
        if display_name not in self._list_id_cache:
            raise ValueError(f"SharePoint list '{display_name}' not found")
        return self._list_id_cache[display_name]

    # ── List operations ───────────────────────────────────────────────────

    def get_item(self, item_id: str, list_display_name: Optional[str] = None) -> dict:
        """
        Fetch a single item by ID. If list_display_name is omitted the client
        will search all cached list IDs (safe when item IDs are unique across lists).
        """
        site_id = self._get_site_id()
        # If we know the list, go directly
        if list_display_name:
            list_id = self._get_list_id(list_display_name)
            url = f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items/{item_id}?expand=fields"
            r = requests.get(url, headers=self._headers(), timeout=30)
            r.raise_for_status()
            return r.json().get("fields", {})
        # Otherwise try all known lists
        if not self._list_id_cache:
            # Warm the cache
            self._get_list_id("__warmup__")  # will raise ValueError but fills cache
        for lid in self._list_id_cache.values():
            url = f"{self.GRAPH_BASE}/sites/{site_id}/lists/{lid}/items/{item_id}?expand=fields"
            r = requests.get(url, headers=self._headers(), timeout=30)
            if r.status_code == 200:
                return r.json().get("fields", {})
        raise ValueError(f"Item {item_id} not found in any known list")

    def update_item(self, item_id: str, fields: dict, list_display_name: Optional[str] = None) -> None:
        site_id = self._get_site_id()
        if list_display_name:
            list_id = self._get_list_id(list_display_name)
        elif self._list_id_cache:
            list_id = next(iter(self._list_id_cache.values()))
        else:
            raise ValueError("list_display_name required when cache is empty")
        url = f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items/{item_id}/fields"
        r = requests.patch(url, headers=self._headers(), json=fields, timeout=30)
        r.raise_for_status()
        logger.info("Updated SharePoint item %s: %s", item_id, list(fields.keys()))

    def get_pending_items_for_list(self, list_key: str, config: "ListConfig") -> list[dict]:
        """
        Fetch all items in the given list where the status column equals 'Pending'.
        Returns a list of field dicts, each augmented with 'id' and '_list_key'.
        """
        site_id = self._get_site_id()
        list_id = self._get_list_id(config.display_name)
        status_col = config.status_col.replace(" ", "_x0020_")  # OData internal name
        url = (
            f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items"
            f"?expand=fields&$filter=fields/{status_col} eq 'Pending'"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        results = []
        for item in r.json().get("value", []):
            fields = item.get("fields", {})
            fields["id"] = item.get("id", "")
            fields["_list_key"] = list_key
            fields["_list_display_name"] = config.display_name
            results.append(fields)
        return results

    # ── Approval state helpers ────────────────────────────────────────────

    def record_approval_decision(
        self,
        item_id: str,
        step: int,
        approver_name: str,
        approver_email: str,
        decision: str,        # "approved" | "rejected"
        comments: str = "",
        list_display_name: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        fields: dict[str, Any] = {
            f"ApproverStep{step}Name":     approver_name,
            f"ApproverStep{step}Email":    approver_email,
            f"ApproverStep{step}Decision": decision.capitalize(),
            f"ApproverStep{step}Date":     now,
        }
        if comments:
            fields[f"ApproverStep{step}Comments"] = comments
        if decision == "rejected":
            fields["Status"]       = "Rejected"
            fields["RejectedBy"]   = approver_name
            fields["RejectedDate"] = now
        self.update_item(item_id, fields, list_display_name)

    def advance_to_next_step(self, item_id: str, next_step: int, list_display_name: Optional[str] = None) -> None:
        self.update_item(item_id, {
            "CurrentApprovalStep": next_step,
            "Status": "In Progress",
        }, list_display_name)

    def mark_fully_approved(self, item_id: str, list_display_name: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_item(item_id, {
            "Status":            "Approved",
            "FullyApprovedDate": now,
        }, list_display_name)

    def mark_rejected(self, item_id: str, rejected_by: str, list_display_name: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_item(item_id, {
            "Status":       "Rejected",
            "RejectedBy":   rejected_by,
            "RejectedDate": now,
        }, list_display_name)
