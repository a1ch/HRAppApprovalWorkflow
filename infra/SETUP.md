# SharePoint List Setup — HRApprovalRequests

## Required columns

Add these columns to your SharePoint list. Internal names must match exactly.

### Request metadata
| Display Name          | Internal Name         | Type              | Notes                              |
|-----------------------|-----------------------|-------------------|------------------------------------|
| WorkflowKey           | WorkflowKey           | Single line       | e.g. job_req_backfill_budgeted     |
| EmployeeName          | EmployeeName          | Single line       |                                    |
| EmployeeNumber        | EmployeeNumber        | Single line       |                                    |
| InitiatorName         | InitiatorName         | Single line       |                                    |
| InitiatorEmail        | InitiatorEmail        | Single line       |                                    |
| EffectiveDate         | EffectiveDate         | Date              |                                    |
| RequestNotes          | RequestNotes          | Multiple lines    |                                    |

### Dynamic role resolution (filled by submitter)
| Display Name          | Internal Name              | Type        |
|-----------------------|----------------------------|-------------|
| DirectManagerName     | DirectManagerName          | Single line |
| DirectManagerEmail    | DirectManagerEmail         | Single line |
| SecondLevelManagerName| SecondLevelManagerName     | Single line |
| SecondLevelManagerEmail| SecondLevelManagerEmail   | Single line |
| HiringManagerName     | HiringManagerName          | Single line |
| HiringManagerEmail    | HiringManagerEmail         | Single line |
| GMDirectorName        | GMDirectorName             | Single line |
| GMDirectorEmail       | GMDirectorEmail            | Single line |
| ExecutiveName         | ExecutiveName              | Single line |
| ExecutiveEmail        | ExecutiveEmail             | Single line |
| CEOName               | CEOName                    | Single line |
| CEOEmail              | CEOEmail                   | Single line |

### Workflow state (written by the function — do not edit manually)
| Display Name            | Internal Name              | Type        |
|-------------------------|----------------------------|-------------|
| Status                  | Status                     | Choice      | Pending, In Progress, Approved, Rejected, Error |
| WorkflowCategory        | WorkflowCategory           | Single line |
| CurrentApprovalStep     | CurrentApprovalStep        | Number      |
| FullyApprovedDate       | FullyApprovedDate          | Date/Time   |
| RejectedBy              | RejectedBy                 | Single line |
| RejectedDate            | RejectedDate               | Date/Time   |
| ErrorMessage            | ErrorMessage               | Single line |

### Per-step approval records (repeat 0–4 for up to 5 steps)
| Display Name            | Internal Name              | Type        |
|-------------------------|----------------------------|-------------|
| ApproverStep0Name       | ApproverStep0Name          | Single line |
| ApproverStep0Email      | ApproverStep0Email         | Single line |
| ApproverStep0Decision   | ApproverStep0Decision      | Choice      | Approved, Rejected |
| ApproverStep0Date       | ApproverStep0Date          | Date/Time   |
| ApproverStep0Comments   | ApproverStep0Comments      | Multiple lines |
| (repeat for steps 1–4)  |                            |             |

---

## App Registration (Azure AD)

1. Azure Portal → Azure Active Directory → App registrations → New registration
   - Name: `streamflo-hr-approvals`
   - Supported account types: Single tenant

2. Certificates & secrets → New client secret → copy value immediately

3. API permissions → Add:
   - Microsoft Graph → Application permissions:
     - `Sites.ReadWrite.All`  (SharePoint read/write)
     - `Mail.Send`            (send email as shared mailbox)
   - Grant admin consent

4. Copy: Tenant ID, Client ID, Client Secret → add to Key Vault as secrets:
   - `SP-TENANT-ID`
   - `SP-CLIENT-ID`
   - `SP-CLIENT-SECRET`

---

## Deployment steps

```bash
# 1. Login
az login
az account set --subscription <your-subscription-id>

# 2. Create resource group
az group create --name streamflo-hr-rg --location eastus

# 3. Deploy infrastructure
az deployment group create \
  --resource-group streamflo-hr-rg \
  --template-file infra/main.bicep \
  --parameters baseName=streamflo-hr \
               spSiteUrl=https://streamflo.sharepoint.com/sites/HR \
               spListName=HRApprovalRequests \
               mailSenderAddress=hr-approvals@streamflo.com

# 4. Add secrets to Key Vault (get name from deployment output)
az keyvault secret set --vault-name streamflo-hr-kv --name SP-TENANT-ID     --value "<tenant-id>"
az keyvault secret set --vault-name streamflo-hr-kv --name SP-CLIENT-ID     --value "<client-id>"
az keyvault secret set --vault-name streamflo-hr-kv --name SP-CLIENT-SECRET --value "<client-secret>"

# 5. Deploy function code
cd function_app
func azure functionapp publish streamflo-hr-func --python

# 6. Update APPROVAL_BASE_URL in Function App settings with the deployed URL
az functionapp config appsettings set \
  --name streamflo-hr-func \
  --resource-group streamflo-hr-rg \
  --settings APPROVAL_BASE_URL=https://streamflo-hr-func.azurewebsites.net

# 7. Add role email settings
az functionapp config appsettings set \
  --name streamflo-hr-func \
  --resource-group streamflo-hr-rg \
  --settings \
    EMAIL_HR_MANAGER=rlperkins@streamflo.com \
    EMAIL_PAYROLL_MANAGER=gthedford@streamflo.com \
    EMAIL_BENEFITS_SPECIALIST=scarrisalez@streamflo.com \
    EMAIL_HR_GENERALIST=tparashar@streamflo.com
```
