"""
Entra ID (Azure AD) client — resolves users and manager chains via Microsoft Graph.

Env vars are read lazily on first use, not in __init__.

Required App Settings:
  SP_TENANT_ID     - Azure AD tenant ID
  SP_CLIENT_ID     - App registration client ID
  SP_CLIENT_SECRET - App registration client secret
"""

import logging
import os
import time
from typing import Optional

import msal
import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300


class EntraClient:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        # Do NOT read env vars here — read lazily in _credentials()
        self._token: Optional[str] = None
        self._token_time: float = 0.0
        self._user_cache: dict[str, dict] = {}
        self._manager_cache: dict[str, dict] = {}

    def _credentials(self) -> tuple[str, str, str]:
        return (
            os.environ["SP_TENANT_ID"],
            os.environ["SP_CLIENT_ID"],
            os.environ["SP_CLIENT_SECRET"],
        )

    # ── Auth ──────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token and (time.monotonic() - self._token_time) < 3500:
            return self._token
        tenant_id, client_id, client_secret = self._credentials()
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"MSAL auth failed: {result.get('error_description')}")
        self._token = result["access_token"]
        self._token_time = time.monotonic()
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"}

    def _search_headers(self) -> dict:
        return {**self._headers(), "ConsistencyLevel": "eventual"}

    # ── User lookup ───────────────────────────────────────────────────────

    def get_user_by_email(self, email: str) -> dict:
        email = email.strip().lower()
        if email in self._user_cache:
            return self._user_cache[email]
        url = f"{self.GRAPH_BASE}/users/{email}?$select=id,displayName,mail,userPrincipalName,jobTitle"
        r = requests.get(url, headers=self._headers(), timeout=30)
        if r.status_code == 404:
            raise ValueError(f"User not found in Entra by email: {email}")
        r.raise_for_status()
        user = r.json()
        self._user_cache[email] = user
        return user

    def get_user_by_display_name(self, display_name: str) -> dict:
        key = display_name.strip().lower()
        if key in self._user_cache:
            return self._user_cache[key]
        url = (
            f"{self.GRAPH_BASE}/users"
            f"?$filter=displayName eq '{display_name}'"
            "&$select=id,displayName,mail,userPrincipalName,jobTitle"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        results = r.json().get("value", [])
        if not results:
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
            logger.warning("Multiple Entra users matched '%s' — using first", display_name)
        user = results[0]
        self._user_cache[key] = user
        return user

    def get_user(self, email_or_name: str) -> dict:
        if "@" in email_or_name:
            return self.get_user_by_email(email_or_name)
        return self.get_user_by_display_name(email_or_name)

    # ── Manager chain ─────────────────────────────────────────────────────

    def get_manager(self, user_id_or_email: str) -> dict:
        if "@" in user_id_or_email or " " in user_id_or_email:
            user = self.get_user(user_id_or_email)
            user_id = user["id"]
        else:
            user_id = user_id_or_email
        if user_id in self._manager_cache:
            return self._manager_cache[user_id]
        url = f"{self.GRAPH_BASE}/users/{user_id}/manager?$select=id,displayName,mail,userPrincipalName,jobTitle"
        r = requests.get(url, headers=self._headers(), timeout=30)
        if r.status_code == 404:
            raise ValueError(f"No manager set in Entra for user ID: {user_id}")
        r.raise_for_status()
        manager = r.json()
        self._manager_cache[user_id] = manager
        return manager

    def get_manager_chain(self, email_or_name: str, levels: int = 4) -> list[dict]:
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
                break
        return chain

    def resolve_manager_role(self, employee_email_or_name: str, level: int = 0) -> tuple[str, str]:
        chain = self.get_manager_chain(employee_email_or_name, levels=level + 1)
        if len(chain) <= level:
            raise ValueError(
                f"Manager chain for '{employee_email_or_name}' only has {len(chain)} "
                f"level(s) — cannot resolve level {level}."
            )
        manager = chain[level]
        name  = manager.get("displayName") or manager.get("userPrincipalName", "")
        email = manager.get("mail") or manager.get("userPrincipalName", "")
        if not email:
            raise ValueError(f"Manager at level {level} for '{employee_email_or_name}' has no email.")
        return name, email
