# HR Approval Workflow — Next Session TODO

## Context
The app has been refactored to resolve ALL approval chain roles from either
Entra ID (manager chain) or the HR Approval Roles list. Approval chain
Person picker columns are no longer needed on the SharePoint lists and need
to be removed to get under SharePoint's 12 lookup column limit.

Every list is currently over the limit. Removing the columns below will bring
each list to ~6-8 lookups with room to grow.

---

## SharePoint Column Cleanup

### All 6 lists — delete these columns:
- `HR Manager`
- `2nd Level Manager`
- `Benefits Specialist`
- `Payroll Manager`
- `GM Director`

### Leave of Absence
No additional changes needed.

### Offer Letters Request Form — also delete:
- `Executive`
- `Approver` (legacy single-approver field)
- `Reporting Supervisor` (not used by app)
- `Replaced Employee` (not used by app)

### Payroll Change Notice — also delete:
- `Executive`
- `CEO`
- `HR Generalist`
- `Authorized By` (legacy)
- `Approved By` (legacy)
- `New Supervisor` (not used by app)

### Termination Form
No additional changes needed.

### Workforce Requisition Form — also delete:
- `Executive`
- `CEO`
- `Approved By` (legacy, already plain text)
- `Reporting To` (not used by app — confirm with HR first)

### Promotion Title Change With Pay — also delete:
- `Executive`
- `CEO`

---

## After Column Cleanup
1. Run `/api/debug-lookups?code=YOUR_KEY` to confirm all lists are under 12
2. Run `/api/debug-lists?code=YOUR_KEY` to confirm no expected columns are missing
3. Do a full end-to-end test from the Power Apps form:
   - Submit a test item with `WorkflowKey` set
   - Confirm the timer picks it up within 5 min
   - Confirm the approval email arrives at sstubbs@streamflo.com
   - Click Approve and confirm the next step fires
   - Complete the chain and confirm the PDF is generated

## Power Apps Integration
- Power Apps form needs to set `WorkflowKey` on each new item
- `WorkflowKey` must match a key in `approval_matrix.py` (e.g. `loa_personal`)
- `EmployeeEmail` should be set if the employee is a known Entra user
  (enables automatic manager chain lookup)
- `InitiatorName` and `InitiatorEmail` should be set so rejection/approval
  emails go back to the right person

## Debug Endpoints (remove before go-live)
- `/api/health` — confirms host is running
- `/api/debug-roles` — shows what the app read from HR Approval Roles list
- `/api/debug-lists` — column check for all 6 lists
- `/api/debug-lookups` — lookup column count + redundant/legacy analysis
