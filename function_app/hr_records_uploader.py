"""
Uploads the approval record PDF to the HR Records SharePoint document library.

Env vars are read lazily on first use, not in __init__.

Target: https://streamflogroup.sharepoint.com/hrcp/hrst/HR%20Records/
"""

import logging
import os
from datetime import datetime, timezone

import msal
import requests

logger = logging.getLogger(__name__)

SP_HOST      = "streamflogroup.sharepoint.com"
SP_SITE_PATH = "hrcp/hrst"
LIBRARY_NAME = "HR Records"


class HRRecordsUploader:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        # Do NOT read env vars here — read lazily in _credentials()
        self._token    = None
        self._site_id  = None
        self._drive_id = None

    def _credentials(self) -> tuple[str, str, str]:
        return (
            os.environ["SP_TENANT_ID"],
            os.environ["SP_CLIENT_ID"],
            os.environ["SP_CLIENT_SECRET"],
        )

    # ── Auth ──────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token:
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
        return self._token

    def _headers(self, content_type: str = "application/json") -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": content_type}

    # ── Site / Drive resolution ───────────────────────────────────────────

    def _get_site_id(self) -> str:
        if self._site_id:
            return self._site_id
        url = f"{self.GRAPH_BASE}/sites/{SP_HOST}:/{SP_SITE_PATH}"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        self._site_id = r.json()["id"]
        return self._site_id

    def _get_drive_id(self) -> str:
        if self._drive_id:
            return self._drive_id
        site_id = self._get_site_id()
        url = f"{self.GRAPH_BASE}/sites/{site_id}/drives"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        for drive in r.json().get("value", []):
            if drive.get("name", "").lower() == LIBRARY_NAME.lower():
                self._drive_id = drive["id"]
                return self._drive_id
        raise ValueError(f"Document library '{LIBRARY_NAME}' not found.")

    # ── Folder creation ───────────────────────────────────────────────────

    def _ensure_folder(self, folder_path: str) -> None:
        drive_id = self._get_drive_id()
        parts = folder_path.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}".lstrip("/")
            url = f"{self.GRAPH_BASE}/drives/{drive_id}/root:/{current}"
            check = requests.get(url, headers=self._headers(), timeout=30)
            if check.status_code == 404:
                parent = "/".join(current.split("/")[:-1])
                parent_url = (
                    f"{self.GRAPH_BASE}/drives/{drive_id}/root/children" if not parent
                    else f"{self.GRAPH_BASE}/drives/{drive_id}/root:/{parent}:/children"
                )
                payload = {"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "ignore"}
                r = requests.post(parent_url, headers=self._headers(), json=payload, timeout=30)
                if r.status_code not in (200, 201):
                    logger.warning("Could not create folder %s: %s", current, r.text)

    # ── Upload ────────────────────────────────────────────────────────────

    def upload_pdf(self, pdf_bytes: bytes, filename: str, approved_date: str) -> str:
        try:
            dt = datetime.fromisoformat(approved_date.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
        folder_path = dt.strftime("%Y/%m")
        self._ensure_folder(folder_path)
        drive_id    = self._get_drive_id()
        upload_path = f"{folder_path}/{filename}"
        url = f"{self.GRAPH_BASE}/drives/{drive_id}/root:/{upload_path}:/content"
        r = requests.put(url, headers=self._headers(content_type="application/pdf"), data=pdf_bytes, timeout=60)
        r.raise_for_status()
        file_data = r.json()
        web_url   = file_data.get("webUrl", "")
        item_id   = file_data.get("id", "")
        logger.info("PDF uploaded: %s (%d bytes)", web_url, len(pdf_bytes))
        if item_id:
            self._set_file_metadata(item_id)
        return web_url

    def _set_file_metadata(self, item_id: str) -> None:
        drive_id = self._get_drive_id()
        url = f"{self.GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
        try:
            requests.patch(url, headers=self._headers(), json={
                "description": "HR approval record — generated automatically by Stream-Flo HR Approval System",
            }, timeout=30)
        except Exception as e:
            logger.warning("Could not set file metadata: %s", e)
