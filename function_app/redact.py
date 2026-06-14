"""
Helpers to keep personal data out of logs / Application Insights.

HR requests carry names, emails, and approval decisions. Those must not land in
App Insights (which is typically readable by more people than the HR lists).
Log the item id instead of names/emails where possible; where a little
traceability is wanted, log a masked email via mask_email().
"""


def mask_email(email: str) -> str:
    """j.smith@streamflo.com -> 'j***@streamflo.com'. Empty/invalid -> '***'."""
    e = (email or "").strip()
    if not e:
        return ""
    if "@" not in e:
        return "***"
    local, _, domain = e.partition("@")
    head = local[0] if local else ""
    return f"{head}***@{domain}"
