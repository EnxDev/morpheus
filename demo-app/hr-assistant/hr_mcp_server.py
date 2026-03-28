"""HR Tool Server — exposes HR operations as a real MCP server.

This simulates the MCP tool server of a real company.
Morpheus MCP Proxy discovers these tools and wraps them.

Run:
    cd demo-app/hr-assistant
    python hr_mcp_server.py

Exposes tools on port 5010 via JSON-RPC (MCP protocol).
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import date

from fake_db import (
    get_employee,
    get_employee_by_name,
    get_leave_balance,
    get_leave_requests,
    get_attendance,
    get_payslips,
    get_department_employees,
    LeaveStatus,
)

# ── Tool definitions (what Morpheus discovers via tools/list) ────────

HR_TOOLS = [
    {
        "name": "query_leave_balance",
        "description": "Get remaining leave days for an employee",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee ID (e.g. E003)"},
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "request_leave",
        "description": "Submit a leave request for an employee",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee ID"},
                "period": {"type": "string", "description": "Requested period (e.g. '14-16 April')"},
                "leave_type": {"type": "string", "description": "Type: vacation, sick_leave, personal_leave"},
            },
            "required": ["employee_id", "period"],
        },
    },
    {
        "name": "approve_leave",
        "description": "Approve or reject a pending leave request",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Leave request ID"},
                "decision": {"type": "string", "description": "approve or reject"},
            },
            "required": ["request_id", "decision"],
        },
    },
    {
        "name": "query_payroll",
        "description": "Get payroll data for an employee",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee ID"},
                "month": {"type": "string", "description": "Month code (e.g. 2025-03)"},
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "query_attendance",
        "description": "Get attendance records for an employee",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee ID"},
                "limit": {"type": "integer", "description": "Number of records (default 10)"},
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "send_notification",
        "description": "Send a notification email to an employee",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_employee_id": {"type": "string", "description": "Recipient employee ID"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
            },
            "required": ["to_employee_id", "subject", "body"],
        },
    },
    {
        "name": "delete_leave_requests",
        "description": "Delete pending leave requests (admin only)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "Employee ID (or 'all')"},
                "status_filter": {"type": "string", "description": "Filter by status: pending, approved, all"},
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "export_all_salaries",
        "description": "Export salary data for all employees (HR admin only)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "csv or json"},
            },
        },
    },
]


# ── Tool execution (the real logic) ─────────────────────────────────

def _date_str(d: date) -> str:
    return d.isoformat()


def execute_tool(name: str, args: dict) -> dict:
    """Execute an HR tool and return the result."""

    if name == "query_leave_balance":
        emp_id = args.get("employee_id", "")
        emp = get_employee(emp_id)
        balance = get_leave_balance(emp_id)
        if not emp:
            return {"error": f"Employee {emp_id} not found"}
        return {
            "employee": emp.name,
            "employee_id": emp_id,
            "balance": balance or {},
        }

    if name == "request_leave":
        emp_id = args.get("employee_id", "")
        emp = get_employee(emp_id)
        if not emp:
            return {"error": f"Employee {emp_id} not found"}
        return {
            "status": "submitted",
            "employee": emp.name,
            "period": args.get("period", "not specified"),
            "message": f"Leave request submitted for {emp.name}. Status: pending.",
        }

    if name == "approve_leave":
        return {
            "status": "approved",
            "request_id": args.get("request_id", "unknown"),
            "message": "Leave request approved (demo).",
        }

    if name == "query_payroll":
        emp_id = args.get("employee_id", "")
        emp = get_employee(emp_id)
        if not emp:
            return {"error": f"Employee {emp_id} not found"}
        month = args.get("month")
        slips = get_payslips(emp_id, month)
        if slips:
            latest = slips[-1]
            return {
                "employee": emp.name,
                "month": latest.month,
                "gross": latest.gross,
                "net": latest.net,
                "deductions": latest.deductions,
                "bonus": latest.bonus,
            }
        return {"employee": emp.name, "message": "No payslip found"}

    if name == "query_attendance":
        emp_id = args.get("employee_id", "")
        emp = get_employee(emp_id)
        if not emp:
            return {"error": f"Employee {emp_id} not found"}
        limit = args.get("limit", 10)
        records = get_attendance(emp_id)[:limit]
        return {
            "employee": emp.name,
            "days": len(records),
            "total_hours": round(sum(r.hours_worked for r in records), 1),
            "remote_days": sum(1 for r in records if r.remote),
        }

    if name == "send_notification":
        to_id = args.get("to_employee_id", "")
        emp = get_employee(to_id)
        return {
            "status": "sent",
            "to": emp.name if emp else to_id,
            "subject": args.get("subject", ""),
            "message": f"Notification sent to {emp.name if emp else to_id} (demo).",
        }

    if name == "delete_leave_requests":
        emp_id = args.get("employee_id", "all")
        pending = get_leave_requests(status=LeaveStatus.PENDING)
        return {
            "status": "deleted",
            "count": len(pending),
            "message": f"Deleted {len(pending)} pending leave requests (demo).",
        }

    if name == "export_all_salaries":
        return {
            "status": "exported",
            "format": args.get("format", "csv"),
            "employee_count": 15,
            "message": "All salary data exported (demo).",
        }

    return {"error": f"Unknown tool: {name}"}


# ── MCP JSON-RPC handler ────────────────────────────────────────────

class HRMCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        method = body.get("method", "")
        req_id = body.get("id", 1)

        if method == "tools/list":
            result = {"tools": HR_TOOLS}
        elif method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "unknown")
            arguments = params.get("arguments", {})
            tool_result = execute_tool(tool_name, arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(tool_result, default=str)}],
            }
        else:
            result = {"error": f"Unknown method: {method}"}

        response = {"jsonrpc": "2.0", "result": result, "id": req_id}
        payload = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Show logs for demo visibility
        print(f"[HR MCP] {args[0]}")


if __name__ == "__main__":
    PORT = 5010
    print(f"HR MCP Tool Server starting on port {PORT}...")
    print(f"Tools: {[t['name'] for t in HR_TOOLS]}")
    print(f"Morpheus proxy can connect to: http://127.0.0.1:{PORT}")
    server = HTTPServer(("127.0.0.1", PORT), HRMCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\nShutdown.")
