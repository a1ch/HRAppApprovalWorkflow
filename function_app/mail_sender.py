"""
Sends email via Microsoft Graph API using a shared mailbox or service account.
No SMTP configuration needed — uses the same service principal as SharePoint.

Required App Settings:
  MAIL_SENDER_ADDRESS  - e.g. hr-approvals@streamflo.com (shared mailbox)
  SP_TENANT_ID / SP_CLIENT_ID / SP_CLIENT_SECRET  (reused from sharepoint_client)
"""

import os
import logging
from dataclasses import dataclass

import msal
import requests

from email_templates import EmailMessage

logger = logging.getLogger(__name__)


class GraphMailSender:
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.tenant_id = os.environ["SP_TENANT_ID"]
        self.client_id = os.environ["SP_CLIENT_ID"]
        self.client_secret = os.environ["SP_CLIENT_SECRET"]
        self.sender = os.environ["MAIL_SENDER_ADDRESS"]
        self._token = None

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

    def send(self, message: EmailMessage, cc: list[str] | None = None) -> None:
        token = self._get_token()
        payload = {
            "message": {
                "subject": message.subject,
                "body": {
                    "contentType": "HTML",
                    "content": message.body_html,
                },
                "toRecipients": [
                    {"emailAddress": {"address": message.to}}
                ],
                "ccRecipients": [
                    {"emailAddress": {"address": addr}} for addr in (cc or [])
                ],
            },
            "saveToSentItems": True,
        }
        url = f"{self.GRAPH_BASE}/users/{self.sender}/sendMail"
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if r.status_code == 202:
            logger.info("Email sent to %s: %s", message.to, message.subject)
        else:
            logger.error("Failed to send email to %s: %s %s", message.to, r.status_code, r.text)
            r.raise_for_status()

    def send_batch(self, messages: list[EmailMessage]) -> None:
        for msg in messages:
            try:
                self.send(msg)
            except Exception as e:
                logger.error("Failed sending to %s: %s", msg.to, e)
