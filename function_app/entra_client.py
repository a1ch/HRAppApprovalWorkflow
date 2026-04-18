"""
Entra ID (Azure AD) client — resolves users and manager chains via Microsoft Graph.

Used to look up:
  - A user by email or display name
  - Their direct manager (Direct Manager role)
  - Their manager's manager (2nd Level Manager role)
  - Further up the chain if needed (GM/Director, Executive, CEO)

Reuses the same MSAL credentials as sharepoint_client.py.
Results are cached per-instance to avoid redundant Graph calls within a
single function invocation.

Required App Settings:
  SP_TENANT_ID    - Azure AD tenant ID
  SP_CLIENT_ID    - App registration client ID
  SP_CLIENT_SECRET - App registration client secret
"""

import logging
import os
import time
from typing import Optional

import msal
import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes


class EntraClient:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.tenant_id     = os.environ["SP_TENANT_ID"]
        self.client_id     = os.environ["SP_CLIENT_ID"]
        self.client_secret = os.environ["SP_CLIENT_SECRET"]
        self._token: Optional[str] = None
        self._token_time: float = 0.0
        self._user_cache: dict[str, dict] = {}   # email/name -> user dict
        self._manager_cache: dict[str, dict] = {}  # user_id -> manager dict

    # ── Auth ──────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token and (time.monotonic() - self._token_time) < 3500:
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
        self._token_time = time.monotonic()
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _search_headers(self) -> dict:
        """Headers required for $search queries."""
        return {
            **self._headers(),
            "ConsistencyLevel": "eventual",
        }

    # ── User lookup ───────────────────────────────────────────────────────

    def get_user_by_email(self, email: str) -> dict:
        """
        Look up a user by their UPN / email address.
        Returns a dict with id, displayName, mail, userPrincipalName.
        Raises ValueError if not found.
        """
        email = email.strip().lower()
        if email in self._user_cache:
            return self._user_cache[email]

        url = (
            f"{self.GRAPH_BASE}/users/{email}"
            "?$select=id,displayName,mail,userPrincipalName,jobTitle"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        if r.status_code == 404:
            raise ValueError(f"User not found in Entra by email: {email}")
        r.raise_for_status()
        user = r.json()
        self._user_cache[email] = user
        logger.debug("Entra user resolved by email: %s -> %s", email, user.get("displayName"))
        return user

    def get_user_by_display_name(self, display_name: str) -> dict:
        """
        Search for a user by display name.
        Returns the first match. Raises ValueError if not found or ambiguous.
        """
        key = display_name.strip().lower()
        if key in self._user_cache:
            return self._user_cache[key]

        # Try exact filter first
        url = (
            f"{self.GRAPH_BASE}/users"
            f"?$filter=displayName eq '{display_name}'"
            "&$select=id,displayName,mail,userPrincipalName,jobTitle"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        results = r.json().get("value", [])

        if not results:
            # Fall back to search
            url = (
                f"{self.GRAPH_BASE}/users"
                f"?$search=\"displayName:{display_name}\""
                "&$select=id,displayName,mail,userPrincipalName,jobTitle"
                "&$orderby=displayName"
            )
            r = requests.get(url, headers=self._search_headers(), timeout=30)
            r.raise_for_status()
            results = r.json().get("value", [])

        if not results:
            raise ValueError(f"User not found in Entra by display name: '{display_name}'")

        if len(results) > 1:
            logger.warning(
                "Multiple Entra users matched display name '%s': %s — using first match",
                display_name,
                [u.get("mail") for u in results],
            )

        user = results[0]
        self._user_cache[key] = user
        logger.debug("Entra user resolved by name: %s -> %s", display_name, user.get("mail"))
        return user

    def get_user(self, email_or_name: str) -> dict:
        """
        Resolve a user by email if it looks like an email, otherwise by display name.
        """
        if "@" in email_or_name:
            return self.get_user_by_email(email_or_name)
        return self.get_user_by_display_name(email_or_name)

    # ── Manager chain ─────────────────────────────────────────────────────

    def get_manager(self, user_id_or_email: str) -> dict:
        """
        Get the direct manager of a user.
        user_id_or_email can be an Entra object ID or email/UPN.
        Returns a dict with id, displayName, mail, userPrincipalName.
        Raises ValueError if no manager is set.
        """
        # Resolve to user first if it's an email
        if "@" in user_id_or_email or " " in user_id_or_email:
            user = self.get_user(user_id_or_email)
            user_id = user["id"]
        else:
            user_id = user_id_or_email

        if user_id in self._manager_cache:
            return self._manager_cache[user_id]

        url = (
            f"{self.GRAPH_BASE}/users/{user_id}/manager"
            "?$select=id,displayName,mail,userPrincipalName,jobTitle"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        if r.status_code == 404:
            raise ValueError(f"No manager set in Entra for user ID: {user_id}")
        r.raise_for_status()
        manager = r.json()
        self._manager_cache[user_id] = manager
        logger.debug(
            "Entra manager resolved: %s -> %s (%s)",
            user_id, manager.get("displayName"), manager.get("mail"),
        )
        return manager

    def get_manager_chain(self, email_or_name: str, levels: int = 4) -> list[dict]:
        """
        Walk up the manager chain from a user, returning up to `levels` managers.
        Index 0 = direct manager, 1 = manager's manager, etc.
        Stops early if no further manager is set.

        Returns list of dicts with id, displayName, mail, userPrincipalName.
        """
        chain = []
        try:
            current = self.get_user(email_or_name)
        except ValueError as e:
            logger.warning("Could not resolve starting user for manager chain: %s", e)
            return chain

        for level in range(levels):
            try:
                manager = self.get_manager(current["id"])
                chain.append(manager)
                current = manager
            except ValueError:
                logger.debug(
                    "Manager chain ended at level %d for %s",
                    level, email_or_name,
                )
                break

        return chain

    # ── Role resolution helpers ───────────────────────────────────────────

    def resolve_manager_role(
        self,
        employee_email_or_name: str,
        level: int = 0,
    ) -> tuple[str, str]:
        """
        Resolve a manager role for an employee by walking their Entra manager chain.

        level=0 -> Direct Manager
        level=1 -> 2nd Level Manager (manager's manager)
        level=2 -> 3rd level (GM/Director equivalent)
        level=3 -> 4th level (Executive equivalent)

        Returns (display_name, email).
        Raises ValueError if the chain doesn't reach the requested level.
        """
        chain = self.get_manager_chain(employee_email_or_name, levels=level + 1)
        if len(chain) <= level:
            raise ValueError(
                f"Manager chain for '{employee_email_or_name}' only has {len(chain)} "
                f"level(s) — cannot resolve level {level} (0-indexed)."
            )
        manager = chain[level]
        name  = manager.get("displayName") or manager.get("userPrincipalName", "")
        email = manager.get("mail") or manager.get("userPrincipalName", "")
        if not email:
            raise ValueError(
                f"Manager at level {level} for '{employee_email_or_name}' has no email in Entra."
            )
        return name, email
