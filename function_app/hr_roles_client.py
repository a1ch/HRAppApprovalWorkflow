"""
HR Approval Roles list client.

Resolves static role → (name, email) by querying the 'HR Approval Roles'
SharePoint list. Falls back to env vars if the list lookup fails, so
deployment isn't broken if the list hasn't been set up yet.

List columns expected:
  Title    — role name  e.g. "HR Manager"
  Name     — person's display name
  Email    — M365 email address
  Active   — Yes/No column (only Active=Yes rows are returned)
  Company  — "Stream-Flo USA LLC" | "Master Flo Valve USA Inc." | "Dycor" | "All"

Rows are cached for CACHE_TTL_SECONDS to avoid hammering Graph API on every
approval step. Cache is per-process (Azure Function instance), so it resets
on cold start — which is fine, cold starts are infrequent.
"""

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300   # 5 minutes


class HRRolesClient:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, sp_client):
        """
        sp_client — a SharePointClient instance (reuses its token + site resolution).
        """
        self._sp = sp_client
        self._list_name = os.environ.get("HR_ROLES_LIST_NAME", "HR Approval Roles")
        self._cache: dict[str, list[dict]] = {}   # role -> list of {name, email}
        self._cache_time: float = 0.0
        self._list_id: Optional[str] = None

    # ── Cache management ──────────────────────────────────────────────────

    def _is_cache_valid(self) -> bool:
        return (time.monotonic() - self._cache_time) < CACHE_TTL_SECONDS

    def _load_cache(self) -> None:
        """Fetch all active rows from HR Approval Roles and build the cache."""
        site_id = self._sp._get_site_id()
        list_id = self._get_roles_list_id(site_id)

        url = (
            f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items"
            "?expand=fields"
            "&$filter=fields/Active eq 1"
            "&$select=fields"
        )
        r = requests.get(url, headers=self._sp._headers(), timeout=30)
        r.raise_for_status()

        rows = r.json().get("value", [])
        cache: dict[str, list[dict]] = {}

        for item in rows:
            fields = item.get("fields", {})
            role  = (fields.get("Title") or "").strip()
            name  = (fields.get("Name") or "").strip()
            email = (fields.get("Email") or "").strip()
            if not role or not email:
                continue
            cache.setdefault(role, []).append({"name": name or role, "email": email})

        self._cache = cache
        self._cache_time = time.monotonic()
        logger.info(
            "HR Approval Roles cache loaded: %d roles, %d total entries",
            len(cache), sum(len(v) for v in cache.values()),
        )

    def _get_roles_list_id(self, site_id: str) -> str:
        if self._list_id:
            return self._list_id
        url = f"{self.GRAPH_BASE}/sites/{site_id}/lists"
        r = requests.get(url, headers=self._sp._headers(), timeout=30)
        r.raise_for_status()
        for lst in r.json().get("value", []):
            if lst["displayName"].lower() == self._list_name.lower():
                self._list_id = lst["id"]
                return self._list_id
        raise ValueError(
            f"HR Approval Roles list '{self._list_name}' not found. "
            "Check HR_ROLES_LIST_NAME app setting."
        )

    # ── Public API ────────────────────────────────────────────────────────

    def get_role_entries(self, role: str) -> list[dict]:
        """
        Returns all active entries for a role as a list of {name, email} dicts.
        Returns [] if the role is not found.
        Raises on network/auth error.
        """
        if not self._is_cache_valid():
            self._load_cache()
        return self._cache.get(role, [])

    def resolve_role(self, role: str) -> tuple[str, str]:
        """
        Returns (name, email) for a role. If multiple active entries exist,
        returns the first one (all receive emails via send_batch upstream).
        Raises ValueError if the role has no active entries.
        """
        entries = self.get_role_entries(role)
        if not entries:
            raise ValueError(
                f"No active entry for role '{role}' in HR Approval Roles list. "
                "Add an active row for this role before processing requests."
            )
        return entries[0]["name"], entries[0]["email"]

    def get_all_emails_for_role(self, role: str) -> list[tuple[str, str]]:
        """
        Returns all (name, email) pairs for a role — used for notify-only roles
        where every active person should receive the FYI email.
        """
        return [(e["name"], e["email"]) for e in self.get_role_entries(role)]

    def invalidate_cache(self) -> None:
        """Force a fresh fetch on the next lookup — call after HR list changes."""
        self._cache_time = 0.0
