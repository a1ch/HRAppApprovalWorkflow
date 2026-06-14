"""
HMAC signing for approval / rejection action links.

Approval emails contain links that let an approver record a decision WITHOUT
signing in (the /api/approval-action and /api/rejection-form routes are
AuthLevel.ANONYMOUS). On their own those links are forgeable: every parameter
(request_id, approver, action, list_key) sits in the query string, request_id
is a small integer, and an approver's email is knowable from the HR Approval
Roles list. Anyone could craft a URL that approves on someone else's behalf.

To close that gap, every link carries an HMAC-SHA256 signature over its
parameters. The server recomputes the signature on each click and rejects the
request unless it matches (constant-time compare). The endpoints stay anonymous,
but the parameters can no longer be tampered with or forged.

The signing key lives in Key Vault as APPROVAL-SIGNING-KEY and is surfaced to the
Function App as the APPROVAL_SIGNING_KEY app setting. Rotating it invalidates all
outstanding links (an approver would simply need the most recent email), which is
an acceptable trade-off.
"""

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

_ENV_KEY = "APPROVAL_SIGNING_KEY"


def _secret() -> bytes:
    key = os.environ.get(_ENV_KEY, "")
    if not key:
        raise RuntimeError(
            f"{_ENV_KEY} is not set — approval links cannot be signed or verified. "
            "Add it to Key Vault (APPROVAL-SIGNING-KEY) and the Function App settings."
        )
    return key.encode("utf-8")


def _canonical(request_id: str, approver: str, action: str, list_key: str) -> bytes:
    """Canonical message that gets signed. Order and separator are fixed — any
    change here invalidates every previously issued signature.

    `approver` is lower-cased so the signature matches the case-insensitive
    approver check the orchestrator already performs.
    """
    return "|".join([
        (request_id or "").strip(),
        (approver or "").strip().lower(),
        (action or "").strip().lower(),
        (list_key or "").strip(),
    ]).encode("utf-8")


def sign(request_id: str, approver: str, action: str, list_key: str = "") -> str:
    """Return a hex HMAC-SHA256 signature for the given link parameters."""
    return hmac.new(
        _secret(),
        _canonical(request_id, approver, action, list_key),
        hashlib.sha256,
    ).hexdigest()


def verify(request_id: str, approver: str, action: str, list_key: str,
           signature: str) -> bool:
    """Constant-time check that `signature` matches the given parameters.

    Returns False (never raises) on a missing signature or a missing signing
    key, so callers can treat any failure as "reject this request".
    """
    if not signature:
        return False
    try:
        expected = sign(request_id, approver, action, list_key)
    except RuntimeError:
        logger.exception("Cannot verify approval link signature — signing key missing")
        return False
    return hmac.compare_digest(expected, signature.strip())
