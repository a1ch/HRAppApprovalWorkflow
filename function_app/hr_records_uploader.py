"""
Uploads the approval record PDF to the HR Records SharePoint document library.

Target: https://streamflogroup.sharepoint.com/hrcp/hrst/HR%20Records/

Files are saved under a year/month folder:
  HR Records/2026/04/ApprovalRecord_SmithJohn_BackfillBudgeted_20260411.pdf

The SharePoint list item is then updated with a direct link to the file.

Reuses the same MSAL service principal as sharepoint_client.py —
no extra credentials needed.
"""

import logging
import os
from datetime import datetime, timezone

import msal
import requests

logger = logging.getLogger(__name__)

# Derived from the URL the user provided:
# https://streamflogroup.sharepoint.com/hrcp/hrst/HR%20Records/Forms/AllItems.aspx
SP_HOST        = "streamflogroup.sharepoint.com"
SP_SITE_PATH   = "hrcp/hrst"          # site-relative path
LIBRARY_NAME   = "HR Records"         # display name of the document library


class HRRecordsUploader:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.tenant_id     = os.environ["SP_TENANT_ID"]
        self.client_id     = os.environ["SP_CLIENT_ID"]
        self.client_secret = os.environ["SP_CLIENT_SECRET"]
        self._token        = None
        self._site_id      = None
        self._drive_id     = None

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

    def _headers(self, content_type: str = "application/json") -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": content_type,
        }

    # ── Site / Drive resolution ───────────────────────────────────────────

    def _get_site_id(self) -> str:
        if self._site_id:
            return self._site_id
        url = f"{self.GRAPH_BASE}/sites/{SP_HOST}:/{SP_SITE_PATH}"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        self._site_id = r.json()["id"]
        logger.info("Resolved HR Records site ID: %s", self._site_id)
        return self._site_id

    def _get_drive_id(self) -> str:
        if self._drive_id:
            return self._drive_id
        site_id = self._get_site_id()
        url = f"{self.GRAPH_BASE}/sites/{site_id}/drives"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        drives = r.json().get("value", [])
        for drive in drives:
            if drive.get("name", "").lower() == LIBRARY_NAME.lower():
                self._drive_id = drive["id"]
                logger.info("Resolved HR Records drive ID: %s", self._drive_id)
                return self._drive_id
        raise ValueError(
            f"Document library '{LIBRARY_NAME}' not found at {SP_HOST}/{SP_SITE_PATH}. "
            f"Available libraries: {[d.get('name') for d in drives]}"
        )

    # ── Folder creation ───────────────────────────────────────────────────

    def _ensure_folder(self, folder_path: str) -> None:
        """
        Creates year/month folders if they don't exist.
        folder_path example: "2026/04"
        Graph API PUT to a folder path creates it (and parents) automatically.
        """
        drive_id = self._get_drive_id()
        parts = folder_path.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}".lstrip("/")
            url = f"{self.GRAPH_BASE}/drives/{drive_id}/root:/{current}"
            check = requests.get(url, headers=self._headers(), timeout=30)
            if check.status_code == 404:
                # Create the folder
                parent = "/".join(current.split("/")[:-1])
                parent_url = (
                    f"{self.GRAPH_BASE}/drives/{drive_id}/root/children"
                    if not parent
                    else f"{self.GRAPH_BASE}/drives/{drive_id}/root:/{parent}:/children"
                )
                payload = {
                    "name": part,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "ignore",
                }
                r = requests.post(parent_url, headers=self._headers(), json=payload, timeout=30)
                if r.status_code not in (200, 201):
                    logger.warning("Could not create folder %s: %s", current, r.text)

    # ── Upload ────────────────────────────────────────────────────────────

    def upload_pdf(
        self,
        pdf_bytes: bytes,
        filename: str,
        approved_date: str,
    ) -> str:
        """
        Uploads the PDF to HR Records/{year}/{month}/{filename}.
        Returns the web URL of the uploaded file.
        """
        try:
            dt = datetime.fromisoformat(approved_date.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)

        folder_path = dt.strftime("%Y/%m")
        self._ensure_folder(folder_path)

        drive_id = self._get_drive_id()
        upload_path = f"{folder_path}/{filename}"

        # For files under 4MB, simple PUT upload is fine
        # Approval PDFs will always be well under 4MB
        url = f"{self.GRAPH_BASE}/drives/{drive_id}/root:/{upload_path}:/content"
        r = requests.put(
            url,
            headers=self._headers(content_type="application/pdf"),
            data=pdf_bytes,
            timeout=60,
        )
        r.raise_for_status()

        file_data = r.json()
        web_url = file_data.get("webUrl", "")
        item_id = file_data.get("id", "")

        logger.info(
            "PDF uploaded to HR Records/%s/%s — %d bytes — URL: %s",
            folder_path, filename, len(pdf_bytes), web_url,
        )

        # Set file metadata
        if item_id:
            self._set_file_metadata(item_id, filename)

        return web_url

    def _set_file_metadata(self, item_id: str, filename: str) -> None:
        """Tag the file with source system info."""
        drive_id = self._get_drive_id()
        url = f"{self.GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
        payload = {
            "description": "HR approval record — generated automatically by Stream-Flo HR Approval System",
        }
        try:
            requests.patch(url, headers=self._headers(), json=payload, timeout=30)
        except Exception as e:
            logger.warning("Could not set file metadata: %s", e)
