"""
Serves the rejection comment form and processes the submission.

Flow:
  1. Approver clicks Reject in their email
  2. Browser opens GET /api/rejection-form?request_id=...&approver=...&list_key=...
  3. A simple HTML form is shown asking for a reason
  4. Approver types reason and clicks Confirm Rejection
  5. POST /api/rejection-form submits the form
  6. Orchestrator records the rejection with the comment
  7. Browser shows a confirmation page
"""


def build_rejection_form(request_id: str, approver_email: str, list_key: str,
                          employee_name: str, request_type: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reject Request — Stream-Flo HR</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; background: #f5f5f5; display: flex;
         align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 40px 48px; max-width: 520px;
           width: 100%; border: 1px solid #e0e0e0; }}
  .header {{ margin-bottom: 28px; }}
  .header h1 {{ font-size: 20px; color: #1a1a1a; margin-bottom: 6px; }}
  .header p {{ font-size: 13px; color: #888; }}
  .detail-box {{ background: #f8f9fa; border-radius: 6px; padding: 14px 18px;
                 margin-bottom: 24px; border-left: 3px solid #c0392b; }}
  .detail-row {{ display: flex; gap: 10px; font-size: 13px; margin-bottom: 6px; }}
  .detail-row:last-child {{ margin-bottom: 0; }}
  .detail-label {{ color: #666; min-width: 110px; font-weight: 600; }}
  .detail-value {{ color: #1a1a1a; }}
  label {{ display: block; font-size: 13px; font-weight: 600; color: #444;
           margin-bottom: 8px; }}
  textarea {{ width: 100%; border: 1px solid #ddd; border-radius: 6px;
              padding: 12px 14px; font-size: 14px; font-family: Arial, sans-serif;
              resize: vertical; min-height: 100px; outline: none; }}
  textarea:focus {{ border-color: #c0392b; }}
  .hint {{ font-size: 12px; color: #999; margin-top: 6px; margin-bottom: 24px; }}
  .btn-row {{ display: flex; gap: 12px; }}
  .btn-confirm {{ background: #c0392b; color: #fff; border: none; border-radius: 6px;
                  padding: 12px 28px; font-size: 14px; font-weight: 600; cursor: pointer; }}
  .btn-confirm:hover {{ background: #a93226; }}
  .btn-cancel {{ background: #fff; color: #666; border: 2px solid #ddd; border-radius: 6px;
                 padding: 12px 28px; font-size: 14px; font-weight: 600; cursor: pointer; }}
  .footer {{ font-size: 12px; color: #bbb; margin-top: 28px; border-top: 1px solid #eee;
             padding-top: 16px; text-align: center; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>Reject Request</h1>
    <p>Stream-Flo USA — HR Approval System</p>
  </div>

  <div class="detail-box">
    <div class="detail-row">
      <span class="detail-label">Request type:</span>
      <span class="detail-value">{request_type}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Employee:</span>
      <span class="detail-value">{employee_name}</span>
    </div>
  </div>

  <form method="POST" action="/api/rejection-form">
    <input type="hidden" name="request_id" value="{request_id}">
    <input type="hidden" name="approver" value="{approver_email}">
    <input type="hidden" name="list_key" value="{list_key}">

    <label for="comments">Reason for rejection</label>
    <textarea id="comments" name="comments"
              placeholder="Please explain why this request is being rejected..."
              required></textarea>
    <p class="hint">This will be included in the notification email to the requester.</p>

    <div class="btn-row">
      <button type="submit" class="btn-confirm">Confirm Rejection</button>
      <button type="button" class="btn-cancel" onclick="window.close()">Cancel</button>
    </div>
  </form>

  <div class="footer">Stream-Flo USA — HR Approval System</div>
</div>
</body>
</html>"""


def build_rejection_confirmed_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rejection Recorded — Stream-Flo HR</title>
<style>
  body {{ font-family: Arial, sans-serif; background: #f5f5f5; display: flex;
         align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #fff; border-radius: 10px; padding: 40px 48px; max-width: 460px;
           text-align: center; border: 1px solid #e0e0e0; }}
  .icon {{ width: 56px; height: 56px; border-radius: 50%; background: #fdf0f0;
           display: flex; align-items: center; justify-content: center;
           font-size: 24px; color: #c0392b; margin: 0 auto 20px; }}
  h1 {{ font-size: 20px; color: #1a1a1a; margin: 0 0 12px; }}
  p {{ font-size: 14px; color: #555; line-height: 1.6; margin: 0; }}
  .footer {{ font-size: 12px; color: #999; margin-top: 24px;
             border-top: 1px solid #eee; padding-top: 16px; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#8635;</div>
  <h1>Rejection Recorded</h1>
  <p>Your decision and comments have been saved. The requester has been notified with your reason.</p>
  <div class="footer">Stream-Flo USA — HR Approval System<br>You may close this window.</div>
</div>
</body>
</html>"""
