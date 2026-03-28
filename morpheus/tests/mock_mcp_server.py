"""Mock MCP server for testing the proxy's dynamic discovery.

Runs on port 5010 and responds to tools/list and tools/call JSON-RPC requests.
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


MOCK_TOOLS = [
    {
        "name": "send_email",
        "description": "Send an email to a recipient",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get weather for a location",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
            },
            "required": ["location"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "temperature": {"type": "number"},
                "condition": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["temperature", "condition", "location"],
        },
    },
    {
        "name": "read_file",
        "description": "Read contents of a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "delete_repo",
        "description": "Delete a repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Repository name"},
            },
            "required": ["repo_name"],
        },
    },
]


class MockMCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        method = body.get("method", "")
        req_id = body.get("id", 1)

        if method == "tools/list":
            result = {"tools": MOCK_TOOLS}
        elif method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "unknown")
            arguments = params.get("arguments", {})
            result = {
                "content": [{"type": "text", "text": f"Mock result for {tool_name}({arguments})"}],
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
        pass  # Suppress logs during tests


def start_mock_server(port: int = 5010) -> tuple[HTTPServer, threading.Thread]:
    """Start the mock MCP server in a background thread. Returns (server, thread)."""
    server = HTTPServer(("127.0.0.1", port), MockMCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    print("Starting mock MCP server on port 5010...")
    server, thread = start_mock_server()
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
