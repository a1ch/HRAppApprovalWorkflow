"""
HR Approval Roles list client.

Resolves static role → (name, email) by querying the 'HR Approval Roles'
SharePoint list.

List columns expected:
  Role     — Choice column (NOT Title — Title is a SharePoint system field that
             cannot be changed to a Choice type. Make Title not required and
             hide it from forms, then use this separate Role Choice column.)
             Valid choices must match VALID_ROLES exactly.
  Person   — Person picker column (email extracted automatically from Entra)
  Active   — Yes/No column (only Active=Yes rows are returned)
  Company  — Choice column, valid values defined in VALID_COMPANIES below.

The Role column name defaults to "Role" and is controlled by the
HR_ROLES_ROLE_COL app setting if your list uses a different name.

The Person picker column name is controlled by the HR_ROLES_PERSON_COL app
setting (default: "Person"). If your list uses a different column name update
that setting — no code change needed.

Fallback: if the Person picker yields no email, the client also checks plain
text "Name" and "Email" columns for backwards compatibility.

Rows are cached for CACHE_TTL_SECONDS to avoid hammering Graph API on every
approval step. Cache is per-process (Azure Function instance), so it resets
on cold start — which is fine, cold starts are infrequent.
"""

import logging
import os
import time
from typing import Optional

import requests

from person_field import extract_person

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300   # 5 minutes

# Exact choice values for the Role column on the HR Approval Roles list.
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

# Exact choice values for the Company column on the HR Approval Roles list.
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
        """
        sp_client — a SharePointClient instance (reuses its token + site resolution).
        """
        self._sp         = sp_client
        self._list_name  = os.environ.get("HR_ROLES_LIST_NAME", "HR Approval Roles")
        self._role_col   = os.environ.get("HR_ROLES_ROLE_COL", "Role")
        self._person_col = os.environ.get("HR_ROLES_PERSON_COL", "Person")
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

            # Read from the Role choice column (not Title)
            role = (fields.get(self._role_col) or "").strip()

            if not role:
                logger.warning(
                    "HR Approval Roles: row has empty '%s' column — skipping. "
                    "Make sure the Role Choice column is filled in.",
                    self._role_col,
                )
                continue

            # Validate against known roles
            if role not in VALID_ROLES:
                logger.warning(
                    "HR Approval Roles: unknown role '%s' in '%s' column — skipping. "
                    "Valid choices are: %s",
                    role, self._role_col, sorted(VALID_ROLES),
                )
                continue

            # Warn on unknown company values but don't skip — still usable
            company = (fields.get("Company") or "").strip()
            if company and company not in VALID_COMPANIES:
                logger.warning(
                    "HR Approval Roles: unknown company '%s' for role '%s'. "
                    "Valid companies are: %s",
                    company, role, sorted(VALID_COMPANIES),
                )

            # 1. Try Person picker column
            name, email = extract_person(fields, self._person_col)

            # 2. Fall back to plain text Name / Email columns
            if not email:
                email = (fields.get("Email") or "").strip()
            if not name:
                name = (fields.get("Name") or "").strip()

            if not email:
                logger.warning(
                    "HR Approval Roles: row for role '%s' has no email "
                    "(checked Person picker '%s' and Email text column). Skipping.",
                    role, self._person_col,
                )
                continue

            cache.setdefault(role, []).append({
                "name":    name or role,
                "email":   email,
                "company": company,
            })

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
        Returns all active entries for a role as a list of {name, email, company} dicts.
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
                f"Valid roles are: {sorted(VALID_ROLES)}"
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
