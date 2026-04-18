"""
HR Approval Roles list client.

This is the SINGLE SOURCE OF TRUTH for all org-level approver roles.
The app resolves every role except Direct Manager and 2nd Level Manager
from this list. HR maintains it — no code changes needed when people change.

List columns:
  Role     — Choice column (see VALID_ROLES). Do NOT use Title (system field).
  Person   — Person picker (email extracted from Entra automatically)
  Active   — Yes/No
  Company  — Choice (see VALID_COMPANIES)

Valid Role choices:
  HR Manager, Payroll Manager, Benefits Specialist, HR Generalist,
  GM/Director, Executive, CEO, Hiring Manager

Env vars read lazily on first use.

App settings:
  HR_ROLES_LIST_NAME  (default: "HR Approval Roles")
  HR_ROLES_ROLE_COL   (default: "Role")
  HR_ROLES_PERSON_COL (default: "Person")
"""

import logging
import os
import time
from typing import Optional

import requests

from person_field import extract_person

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300

# All roles the HR Approval Roles list can hold.
# Direct Manager and 2nd Level Manager are NOT here — they come from Entra.
VALID_ROLES: frozenset[str] = frozenset({
    "HR Manager",
    "Payroll Manager",
    "Benefits Specialist",
    "HR Generalist",
    "GM/Director",
    "Executive",
    "CEO",
    "Hiring Manager",
})

VALID_COMPANIES: frozenset[str] = frozenset({
    "Master Flo Valve Inc",
    "Master Flo Valve USA",
    "Master Flo Valve UK",
    "Stream-Flo Industries Ltd",
    "Stream-Flo USA LLC",
    "Stream-Flo Group of Companies",
    "Stream-Flo Saudi Arabia",
    "Dycor",
    "All",
})


class HRRolesClient:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, sp_client):
        self._sp         = sp_client
        self._list_name  = os.environ.get("HR_ROLES_LIST_NAME", "HR Approval Roles")
        self._role_col   = os.environ.get("HR_ROLES_ROLE_COL", "Role")
        self._person_col = os.environ.get("HR_ROLES_PERSON_COL", "Person")
        self._cache: dict[str, list[dict]] = {}
        self._cache_time: float = 0.0
        self._list_id: Optional[str] = None

    # ── Cache ────────────────────────────────────────────────────────────

    def _is_cache_valid(self) -> bool:
        return (time.monotonic() - self._cache_time) < CACHE_TTL_SECONDS

    def _load_cache(self) -> None:
        site_id = self._sp._get_site_id()
        list_id = self._get_roles_list_id(site_id)
        url = (
            f"{self.GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items"
            "?expand=fields&$filter=fields/Active eq 1&$select=fields"
        )
        r = requests.get(url, headers=self._sp._headers(), timeout=30)
        r.raise_for_status()

        cache: dict[str, list[dict]] = {}
        for item in r.json().get("value", []):
            fields = item.get("fields", {})
            role   = (fields.get(self._role_col) or "").strip()

            if not role:
                logger.warning("HR Approval Roles: row missing '%s' column", self._role_col)
                continue
            if role not in VALID_ROLES:
                logger.warning(
                    "HR Approval Roles: unknown role '%s' — valid: %s",
                    role, sorted(VALID_ROLES),
                )
                continue

            name, email = extract_person(fields, self._person_col)
            if not email:
                email = (fields.get("Email") or "").strip()
            if not name:
                name  = (fields.get("Name") or "").strip()
            if not email:
                logger.warning("HR Approval Roles: role '%s' has no email — skipping", role)
                continue

            company = (fields.get("Company") or "").strip()
            if company and company not in VALID_COMPANIES:
                logger.warning("HR Approval Roles: unknown company '%s' for role '%s'", company, role)

            cache.setdefault(role, []).append({
                "name":    name or role,
                "email":   email,
                "company": company,
            })

        self._cache      = cache
        self._cache_time = time.monotonic()
        logger.info(
            "HR Approval Roles cache: %d roles, %d entries",
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

    # ── Public API ──────────────────────────────────────────────────

    def get_role_entries(self, role: str) -> list[dict]:
        """All active entries for a role as {name, email, company} dicts."""
        if not self._is_cache_valid():
            self._load_cache()
        return self._cache.get(role, [])

    def resolve_role(self, role: str) -> tuple[str, str]:
        """
        Returns (name, email) for a role.
        Uses the first active entry if multiple exist.
        Raises ValueError if no active entry found.
        """
        entries = self.get_role_entries(role)
        if not entries:
            raise ValueError(
                f"No active entry for role '{role}' in HR Approval Roles list. "
                f"Valid roles: {sorted(VALID_ROLES)}"
            )
        return entries[0]["name"], entries[0]["email"]

    def get_all_emails_for_role(self, role: str) -> list[tuple[str, str]]:
        """All (name, email) pairs for a role — for notify-only fan-out."""
        return [(e["name"], e["email"]) for e in self.get_role_entries(role)]

    def invalidate_cache(self) -> None:
        self._cache_time = 0.0
