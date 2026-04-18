"""
Helpers for extracting name and email from SharePoint Person/People Picker fields
as returned by the Microsoft Graph API.

When Graph expands a Person column named "Employee" it can appear as any of:

  1. Flat email field (Graph profile expansion):
       fields["EmployeeEmail"] = "john.smith@streamflogroup.com"

  2. Lookup sub-object:
       fields["Employee"] = {"LookupId": 42, "LookupValue": "John Smith"}
       fields["EmployeeLookupId"] = "42"
     (no email directly — need a Graph /users call or the initiator's email)

  3. Expanded user object (when $expand=fields includes user details):
       fields["Employee"] = {
           "id": "abc123",
           "displayName": "John Smith",
           "email": "john.smith@streamflogroup.com",
           "userPrincipalName": "john.smith@streamflogroup.com",
       }

The extract_person_email() function handles all three variants.
The extract_person_name() function extracts the display name.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_person_email(fields: dict, col_name: str) -> str:
    """
    Extract the email address from a Person picker column in a Graph API fields dict.

    Tries (in order):
      1. fields["{col_name}Email"]              -- Graph profile expansion flat field
      2. fields["{col_name}"]["email"]          -- expanded user object
      3. fields["{col_name}"]["userPrincipalName"] -- expanded user object fallback
      4. fields["{col_name}LookupValue"]        -- display name only (no email available)

    Returns empty string if email cannot be determined.
    """
    if not col_name:
        return ""

    # 1. Flat email field (most common with Graph profile expansion)
    flat_email = fields.get(f"{col_name}Email", "")
    if flat_email and "@" in flat_email:
        return flat_email.strip()

    # 2 & 3. Sub-object
    sub = fields.get(col_name)
    if isinstance(sub, dict):
        email = sub.get("email") or sub.get("userPrincipalName", "")
        if email and "@" in email:
            return email.strip()

    # 4. No email available from this field
    logger.debug(
        "Could not extract email from Person field '%s'. "
        "Available keys: %s",
        col_name,
        [k for k in fields if k.startswith(col_name)],
    )
    return ""


def extract_person_name(fields: dict, col_name: str) -> str:
    """
    Extract the display name from a Person picker column.

    Tries (in order):
      1. fields["{col_name}DisplayName"]         -- Graph profile expansion
      2. fields["{col_name}"]["displayName"]     -- expanded user object
      3. fields["{col_name}LookupValue"]         -- SharePoint lookup value
      4. fields["{col_name}"]                    -- plain string fallback

    Returns empty string if name cannot be determined.
    """
    if not col_name:
        return ""

    # 1. Flat display name
    flat_name = fields.get(f"{col_name}DisplayName", "")
    if flat_name:
        return flat_name.strip()

    # 2. Sub-object displayName
    sub = fields.get(col_name)
    if isinstance(sub, dict):
        name = sub.get("displayName") or sub.get("LookupValue", "")
        if name:
            return name.strip()

    # 3. LookupValue
    lookup = fields.get(f"{col_name}LookupValue", "")
    if lookup:
        return lookup.strip()

    # 4. Plain string
    if isinstance(sub, str) and sub:
        return sub.strip()

    return ""


def extract_person(fields: dict, col_name: str) -> tuple[str, str]:
    """
    Extract both (name, email) from a Person picker column.
    Returns ("", "") if neither can be determined.
    """
    return extract_person_name(fields, col_name), extract_person_email(fields, col_name)
