"""
SharePoint client — reads new list items and writes approval state back.
Uses MSAL (Microsoft Authentication Library) with a service principal
(client credentials flow) so no user login is required.

Required App Settings (Azure Function App Configuration):
  SP_TENANT_ID        - Azure AD tenant ID
  SP_CLIENT_ID        - App registration client ID
  SP_CLIENT_SECRET    - App registration client secret
  SP_SITE_URL         - e.g. https://streamflo.sharepoint.com/sites/HR
  SP_LIST_NAME        - e.g. HRApprovalRequests
"""

import os
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import msal
import requests

logger = logging.getLogger(__name__)


class SharePointClient:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.tenant_id = os.environ["SP_TENANT_ID"]
        self.client_id = os.environ["SP_CLIENT_ID"]
        self.client_secret = os.environ["SP_CLIENT_SECRET"]
        self.site_url = os.environ["SP_SITE_URL"].rstrip("/")
        self.list_name = os.environ["SP_LIST_NAME"]
        self._token: Optional[str] = None
        self._site_id: Optional[str] = None
        self._list_id: Optional[str] = None

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
        # Strip https:// and split host from path
        without_scheme = self.site_url.replace("https://", "")
        parts = without_scheme.split("/", 1)
        host = parts[0]
        path = parts[1] if len(parts) > 1 else ""
        url = f"{self.GRAPH_BASE}/sites/{host}:/{path}"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        self._site_id = r.json()["id"]
        return self._site_id

    def _get_list_id(self) -> str:
        if self._list_id:
            return self._list_id
        site_id = self._get_site_id()
        url = f"{self.GRAPH_BASE}/sites/{site_id}/lists"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        lists = r.json().get("value", [])
        for lst in lists:
            if lst["displayName"].lower() == self.list_name.lower():
                self._list_id = lst["id"]
                return self._list_id
        raise ValueError(f"SharePoint list '{self.list_name}' not found")

    # ── List operations ───────────────────────────────────────────────────

    def get_item(self, item_id: str) -> dict:
        site_id = self._get_site_id()
        list_id = self._get_list_id()
        url = f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items/{item_id}?expand=fields"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json().get("fields", {})

    def update_item(self, item_id: str, fields: dict) -> None:
        site_id = self._get_site_id()
        list_id = self._get_list_id()
        url = f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items/{item_id}/fields"
        r = requests.patch(url, headers=self._headers(), json=fields, timeout=30)
        r.raise_for_status()
        logger.info("Updated SharePoint item %s: %s", item_id, list(fields.keys()))

    def get_pending_items(self) -> list[dict]:
        """Fetch all list items with Status = 'Pending'."""
        site_id = self._get_site_id()
        list_id = self._get_list_id()
        url = (
            f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items"
            "?expand=fields&$filter=fields/Status eq 'Pending'"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return [item["fields"] for item in r.json().get("value", [])]

    # ── Approval state helpers ────────────────────────────────────────────

    def record_approval_decision(
        self,
        item_id: str,
        step: int,
        approver_name: str,
        approver_email: str,
        decision: str,        # "approved" | "rejected"
        comments: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        fields: dict[str, Any] = {
            f"ApproverStep{step}Name": approver_name,
            f"ApproverStep{step}Email": approver_email,
            f"ApproverStep{step}Decision": decision.capitalize(),
            f"ApproverStep{step}Date": now,
        }
        if comments:
            fields[f"ApproverStep{step}Comments"] = comments
        if decision == "rejected":
            fields["Status"] = "Rejected"
            fields["RejectedBy"] = approver_name
            fields["RejectedDate"] = now
        self.update_item(item_id, fields)

    def advance_to_next_step(self, item_id: str, next_step: int) -> None:
        self.update_item(item_id, {
            "CurrentApprovalStep": next_step,
            "Status": "In Progress",
        })

    def mark_fully_approved(self, item_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_item(item_id, {
            "Status": "Approved",
            "FullyApprovedDate": now,
        })

    def mark_rejected(self, item_id: str, rejected_by: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_item(item_id, {
            "Status": "Rejected",
            "RejectedBy": rejected_by,
            "RejectedDate": now,
        })
