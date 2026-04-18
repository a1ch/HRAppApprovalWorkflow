"""
Minimal build — health check only, to confirm host starts cleanly.
"""

import json
import logging
import sys

import azure.functions as func

logger = logging.getLogger(__name__)
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.function_name("HealthCheck")
@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({
            "status": "ok",
            "service": "hr-approval-func",
            "python": sys.version,
            "sys_path": sys.path,
        }),
        mimetype="application/json",
    )
