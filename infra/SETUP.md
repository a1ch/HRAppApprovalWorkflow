# HR Approval Function App — Setup Guide

Stream-Flo Group | Azure Functions + SharePoint + Microsoft Graph

---

## Overview

This function app replaces Power Automate approval workflows. It monitors 6 SharePoint
lists for new items, drives sequential approval chains via email, generates a PDF audit
record on full approval, and saves it to the HR Records document library.

**The three things you need to set up:**
1. Azure AD App Registration (one-time)
2. SharePoint lists (HR Approval Roles + existing 6 request lists)
3. Azure infrastructure (Function App, Key Vault, App Insights)

---

## 1. Azure AD App Registration

One app registration covers everything — SharePoint, email, and Key Vault.

### Steps

1. **Azure Portal → Azure Active Directory → App registrations → New registration**
   - Name: `streamflo-hr-approvals`
   - Supported account types: Single tenant
   - Redirect URI: leave blank

2. **Certificates & secrets → New client secret**
   - Copy the value immediately — you cannot retrieve it later

3. **API permissions → Add a permission → Microsoft Graph → Application permissions**
   - `Sites.ReadWrite.All` — read/write all 6 approval lists + HR Records library
   - `Mail.Send` — send email as the shared mailbox
   - `User.Read.All` — look up user emails by display name
   - Click **Grant admin consent**

4. **Copy these three values** — you'll need them in step 3:
   - Directory (tenant) ID
   - Application (client) ID
   - Client secret value

> **Can we reuse an existing app registration?**
> Yes — if an existing registration already has `Sites.ReadWrite.All`, `Mail.Send`, and
> `User.Read.All` with admin consent granted, just use its credentials. No need to create
> a new one.

---

## 2. SharePoint Lists

### 2a. HR Approval Roles list (NEW — create this)

**Site:** `https://streamflogroup.sharepoint.com/hrcp/hrst`
**List name:** `HR Approval Roles`

This list is how HR manages who approves what. When someone leaves, set their
row to Active = No. When someone joins, add a new row. No code changes needed.

**Columns to create:**

| Display Name | Type     | Notes                                              |
|--------------|----------|----------------------------------------------------|
| Title        | Single line | The role name — e.g. `HR Manager`              |
| Company      | Choice   | Options: Stream-Flo USA LLC, Master Flo Valve USA Inc., Dycor, All |
| Name         | Single line | Person's display name                          |
| Email        | Single line | Must match their M365 email exactly            |
| Active       | Yes/No   | Default Yes. Set to No when someone leaves.        |
| Notes        | Single line | Optional context                               |

**How multiple people per role works:**
- Add one row per person. Multiple active rows for the same Role + Company = all of them
  receive the email for that step.
- For approval chain roles (HR Manager, Payroll Manager etc.) keep only ONE active person
  per company at a time — whoever clicks Approve/Reject first wins.
- For notification-only roles (Benefits Specialist, HR Generalist) multiple active rows
  is fine — all of them get the FYI email.

**When someone leaves:**
1. Find their row → set Active = No
2. Add a new row for their replacement → Active = Yes
3. Done. Takes effect on the next request.

**Use Company = `All` for shared roles** (e.g. Rae-Lynn covers HR Manager for all three
companies) — the function will match it to any company's request.

**Starter data** is in `HR_Approval_Roles.xlsx` — copy it into this list to get going.

---

### 2b. Add state columns to each of the 6 request lists

The function writes approval progress back to each request list. Add these columns to
**all 6 lists** (Leave of Absence, Employee Offer Letters, Payroll Change Notification,
Termination Form, Workforce Requirement Form, Promotion Title Change With Pay):

| Display Name        | Internal Name       | Type          |
|---------------------|---------------------|---------------|
| WorkflowKey         | WorkflowKey         | Single line   |
| CurrentApprovalStep | CurrentApprovalStep | Number        |
| ApprovalStatus      | ApprovalStatus      | Choice: Pending, In Progress, Approved, Rejected, Error |
| FullyApprovedDate   | FullyApprovedDate   | Date and Time |
| RejectedBy          | RejectedBy          | Single line   |
| RejectedDate        | RejectedDate        | Date and Time |
| ApprovalRecordURL   | ApprovalRecordURL   | Single line   |
| ErrorMessage        | ErrorMessage        | Single line   |

**Per-step approval record columns (add steps 0–4, 5 total):**

| Display Name          | Type          |
|-----------------------|---------------|
| ApproverStep0Name     | Single line   |
| ApproverStep0Email    | Single line   |
| ApproverStep0Decision | Choice: Approved, Rejected |
| ApproverStep0Date     | Date and Time |
| ApproverStep0Comments | Multiple lines |
| (repeat for 1, 2, 3, 4) | |

---

### 2c. HR Records document library

PDFs are saved here after full approval.

**URL:** `https://streamflogroup.sharepoint.com/hrcp/hrst/HR%20Records/`

The function creates year/month subfolders automatically (e.g. `2026/04/`).
Files are named: `ApprovalRecord_SmithJohn_BackfillBudgeted_20260411.pdf`

Make sure the app registration has `Sites.ReadWrite.All` access to this site collection.

---

## 3. Azure Deployment

### Prerequisites
- Azure CLI installed: `winget install Microsoft.AzureCLI`
- Azure Functions Core Tools: `npm install -g azure-functions-core-tools@4`
- Python 3.11

### Steps

```bash
# 1. Login
az login
az account set --subscription <your-subscription-id>

# 2. Create resource group
az group create --name streamflo-hr-rg --location eastus

# 3. Deploy infrastructure (Function App, Key Vault, App Insights, Storage)
az deployment group create \
  --resource-group streamflo-hr-rg \
  --template-file infra/main.bicep \
  --parameters baseName=streamflo-hr \
               spSiteUrl=https://streamflogroup.sharepoint.com/hrcp/hrst \
               mailSenderAddress=hr-approvals@streamflo.com

# 4. Add secrets to Key Vault (get vault name from deployment output)
az keyvault secret set --vault-name streamflo-hr-kv --name SP-TENANT-ID     --value "<tenant-id>"
az keyvault secret set --vault-name streamflo-hr-kv --name SP-CLIENT-ID     --value "<client-id>"
az keyvault secret set --vault-name streamflo-hr-kv --name SP-CLIENT-SECRET --value "<client-secret>"

# 5. Deploy function code
cd function_app
func azure functionapp publish streamflo-hr-func --python

# 6. Update base URL after first deploy
az functionapp config appsettings set \
  --name streamflo-hr-func \
  --resource-group streamflo-hr-rg \
  --settings APPROVAL_BASE_URL=https://streamflo-hr-func.azurewebsites.net

# 7. Set the HR Approval Roles list name
az functionapp config appsettings set \
  --name streamflo-hr-func \
  --resource-group streamflo-hr-rg \
  --settings HR_ROLES_LIST_NAME="HR Approval Roles"

# 8. Set the sender mailbox
az functionapp config appsettings set \
  --name streamflo-hr-func \
  --resource-group streamflo-hr-rg \
  --settings MAIL_SENDER_ADDRESS=hr-approvals@streamflo.com
```

---

## 4. Environment Variables Reference

| Variable               | Where set    | Description                                      |
|------------------------|--------------|--------------------------------------------------|
| SP_TENANT_ID           | Key Vault    | Azure AD tenant ID                               |
| SP_CLIENT_ID           | Key Vault    | App registration client ID                       |
| SP_CLIENT_SECRET       | Key Vault    | App registration client secret                   |
| SP_SITE_URL            | App Settings | `https://streamflogroup.sharepoint.com/hrcp/hrst`|
| MAIL_SENDER_ADDRESS    | App Settings | Shared mailbox address for outbound email        |
| APPROVAL_BASE_URL      | App Settings | Function App URL (set after first deploy)        |
| HR_ROLES_LIST_NAME     | App Settings | Name of the HR Approval Roles SharePoint list    |

> No email addresses are hardcoded anywhere. All role-to-person mappings live in the
> HR Approval Roles SharePoint list and are managed by HR directly.

---

## 5. Role Management (day-to-day)

**Someone leaves:**
→ HR Approval Roles list → find their row → set Active = No

**Someone new joins a role:**
→ HR Approval Roles list → add new row → Active = Yes

**Temporary cover (e.g. someone on leave):**
→ Set original person to Active = No
→ Add cover person as Active = Yes
→ Flip back when they return

**Multiple people in a notification role (e.g. 5 HR Generalists):**
→ Add one row per person, all Active = Yes
→ All 5 receive the FYI email when triggered

**Multiple people in an approval role:**
→ Only one should be Active = Yes at a time per company
→ First person to click Approve or Reject in their email wins

---

## 6. The 6 SharePoint Lists

| List name                        | Workflow type            | List path                            |
|----------------------------------|--------------------------|--------------------------------------|
| Leave of Absence                 | LOA / FMLA / Military    | Lists/Leave%20of%20Absence           |
| Employee Offer Letters           | Candidate offer letters  | Lists/Employee%20Offer%20Letters     |
| Payroll Change Notification      | PCN (10 sub-types)       | Lists/Payroll%20Change%20Notification|
| Termination Form                 | Discharge/Resign/Retire  | Lists/Termination%20Form             |
| Workforce Requirement Form       | Job requisitions         | Lists/Workforce%20Requirement%20Form |
| Promotion Title Change With Pay  | Promotions / rate changes| Lists/Promotion%20Title%20Change%20With%20Pay |

---

## 7. PDF Audit Records

A PDF is generated and saved to HR Records after every fully approved request.

- **Location:** `HR Records/{year}/{month}/ApprovalRecord_{employee}_{type}_{date}.pdf`
- **Contains:** Request details, full approval chain with timestamps, notifications sent
- **Header:** All 3 company logos (Stream-Flo, Master Flo Valve, Dycor)
- **Link emailed:** Requester receives a direct link to the PDF in their approval confirmation

Each of the 6 workflow types has its own PDF template showing the relevant fields
for that request type (e.g. the Termination PDF shows last day worked, severance
eligibility etc. while the Offer Letter PDF shows wage rate, vacation accrual, rotation).
