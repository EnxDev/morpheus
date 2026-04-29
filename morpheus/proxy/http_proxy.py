"""Morpheus HTTP Proxy — exposes the MCP proxy as an HTTP service.

Allows any HTTP client (demo apps, LangChain, n8n, Superset, etc.)
to route tool calls through Morpheus Control 2 without MCP stdio.

Endpoints:
    POST /proxy/call     — call a tool through the proxy
    GET  /proxy/tools    — list discovered tools
    GET  /proxy/status   — proxy health + tool count
    POST /proxy/intent   — set the validated intent for coherence checks

Run:
    cd morpheus
    python proxy/http_proxy.py --real-server http://localhost:5010 --port 5020

    # With API key (recommended):
    MORPHEUS_PROXY_KEY=my-secret python proxy/http_proxy.py --real-server http://localhost:5010

    # Against a streamable-HTTP MCP server (e.g. FastMCP, Superset MCP):
    python proxy/http_proxy.py --real-server http://localhost:5008/mcp --transport streamable_http

    # Or via env var (same effect as --transport):
    MORPHEUS_DOWNSTREAM_TRANSPORT=streamable_http python proxy/http_proxy.py --real-server http://localhost:5008/mcp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from audit.logger import AuditLogger
from controls import ControlManager
from proxy.proxy_server import MorpheusProxy
from proxy.policy_checker import PolicyChecker
from proxy.transport import (
    DownstreamTransport,
    PlainJsonRpcTransport,
    StreamableHttpTransport,
    TRANSPORT_PLAIN_JSONRPC,
    TRANSPORT_STREAMABLE_HTTP,
    VALID_TRANSPORTS,
)


# ── Config ───────────────────────────────────────────────────────────────────

PROXY_API_KEY = os.environ.get("MORPHEUS_PROXY_KEY", "")
MAX_RESPONSE_CHARS = 100_000


# ── State ────────────────────────────────────────────────────────────────────

_proxy: MorpheusProxy | None = None
_control_manager: ControlManager | None = None
_validated_intent: dict | None = None


# ── Request/Response models ──────────────────────────────────────────────────

class ToolCallRequest(BaseModel):
    tool: str
    params: dict = Field(default_factory=dict)
    intent: dict | None = None          # validated intent for coherence check
    controls_active: dict | None = None  # override control state

class IntentSetRequest(BaseModel):
    intent: dict

class ToolCallResponse(BaseModel):
    status: str  # approved, blocked, bypassed, error
    result: dict | None = None
    decision: dict | None = None
    tool: str = ""


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Morpheus HTTP Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Proxy is internal — restrict in production
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Proxy-Key"],
)


# ── Auth middleware ──────────────────────────────────────────────────────────

def _check_auth(request: Request) -> None:
    """Validate API key if configured."""
    if not PROXY_API_KEY:
        return  # No key configured — open access (dev mode)
    key = request.headers.get("X-Proxy-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ")
    if key != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing proxy API key")


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/proxy/call", response_model=ToolCallResponse)
async def proxy_call(req: ToolCallRequest, request: Request):
    """Call a tool through the Morpheus proxy.

    The proxy checks:
    1. Risk classification (L1 — deterministic)
    2. Coherence with validated intent (L2 — optional LLM)
    3. IBAC authorization tuples (if configured)

    Then forwards to the real MCP server or blocks.
    """
    _check_auth(request)

    if _proxy is None:
        raise HTTPException(status_code=503, detail="Proxy not initialized")

    # Use request intent, stored intent, or none
    intent = req.intent or _validated_intent
    controls = req.controls_active
    if controls is None and _control_manager:
        controls = _control_manager.get_controls().to_dict()

    result = _proxy.call_tool(
        tool_name=req.tool,
        arguments=req.params,
        original_intent=intent,
        controls_active=controls,
    )

    # Truncate oversized responses
    if result.get("status") in ("approved", "bypassed") and result.get("result"):
        content = result["result"]
        if isinstance(content, dict):
            text_items = content.get("content", [])
            for item in text_items:
                if isinstance(item, dict) and "text" in item:
                    text = item["text"]
                    if len(text) > MAX_RESPONSE_CHARS:
                        item["text"] = text[:MAX_RESPONSE_CHARS] + "\n[TRUNCATED]"
                        _proxy.logger.log("response_truncated", {
                            "tool": req.tool,
                            "original_chars": len(text),
                        })

    return ToolCallResponse(
        status=result.get("status", "error"),
        result=result.get("result"),
        decision=result.get("decision"),
        tool=req.tool,
    )


@app.get("/proxy/tools")
async def proxy_tools(request: Request):
    """List all discovered tools from the real MCP server."""
    _check_auth(request)
    if _proxy is None:
        raise HTTPException(status_code=503, detail="Proxy not initialized")
    return {
        "tools": _proxy.get_proxied_tools(),
        "count": _proxy.tool_count,
    }


@app.get("/proxy/status")
async def proxy_status(request: Request):
    """Proxy health check."""
    _check_auth(request)
    controls = _control_manager.get_controls().to_dict() if _control_manager else {}
    return {
        "status": "ok",
        "real_server": _proxy.real_server_url if _proxy else None,
        "tool_count": _proxy.tool_count if _proxy else 0,
        "controls": controls,
        "intent_set": _validated_intent is not None,
    }


@app.post("/proxy/intent")
async def proxy_set_intent(req: IntentSetRequest, request: Request):
    """Set the validated intent for coherence checks.

    Call this after Control 1 has validated the user's intent,
    before calling /proxy/call.
    """
    _check_auth(request)
    global _validated_intent
    _validated_intent = req.intent
    _proxy.logger.log("proxy_intent_set", {"intent_fields": list(req.intent.keys())})
    return {"status": "ok", "fields": list(req.intent.keys())}


@app.get("/proxy/audit")
async def proxy_audit(request: Request, last_n: int = 50):
    """Get proxy audit log."""
    _check_auth(request)
    if _proxy is None:
        return {"events": [], "summary": {}}
    return {
        "events": _proxy.logger.last(last_n),
        "summary": _proxy.logger.summary(),
    }


# ── Startup ──────────────────────────────────────────────────────────────────

def _build_transport(real_server_url: str, transport_name: str) -> DownstreamTransport:
    """Construct the chosen downstream transport. Fails loud on unknown name.

    The validity check here is a belt-and-braces guard: argparse's
    ``choices=`` already rejects bad CLI values, but env-var values bypass
    that path, so we validate again before instantiation.
    """
    if transport_name not in VALID_TRANSPORTS:
        raise ValueError(
            f"Unknown downstream transport {transport_name!r}. "
            f"Valid values: {sorted(VALID_TRANSPORTS)}"
        )
    if transport_name == TRANSPORT_STREAMABLE_HTTP:
        return StreamableHttpTransport(real_server_url)
    return PlainJsonRpcTransport(real_server_url)


def init_proxy(real_server_url: str, transport_name: str = TRANSPORT_PLAIN_JSONRPC) -> None:
    """Initialize the proxy connection to the real MCP server."""
    global _proxy, _control_manager

    logger = AuditLogger()
    _control_manager = ControlManager(logger=logger)

    transport = _build_transport(real_server_url, transport_name)
    logger.log("downstream_transport_selected", {
        "transport": transport.name,
        "server_url": real_server_url,
    })

    _proxy = MorpheusProxy(
        real_server_or_transport=transport,
        policy_checker=PolicyChecker(),
        logger=logger,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Morpheus HTTP Proxy")
    parser.add_argument(
        "--real-server",
        default=os.environ.get("MORPHEUS_REAL_SERVER", "http://localhost:5010"),
        help="URL of the real MCP server to proxy",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MORPHEUS_PROXY_PORT", "5020")),
        help="Port for the HTTP proxy (default: 5020)",
    )
    parser.add_argument(
        "--transport",
        default=os.environ.get("MORPHEUS_DOWNSTREAM_TRANSPORT", TRANSPORT_PLAIN_JSONRPC),
        choices=sorted(VALID_TRANSPORTS),
        help=(
            "Downstream MCP wire format. 'plain_jsonrpc' (default) is the "
            "original Morpheus JSON-RPC-over-HTTP dialect used by the demo "
            "servers. 'streamable_http' is the MCP spec's streamable-HTTP "
            "transport, required for servers like FastMCP-in-streamable mode."
        ),
    )
    args = parser.parse_args()

    try:
        init_proxy(args.real_server, args.transport)
    except ValueError as exc:
        # Unknown transport value coming via the env var (argparse's
        # choices= already guards the CLI path).
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"Morpheus HTTP Proxy starting...", file=sys.stderr)
    print(f"  Real server: {args.real_server}", file=sys.stderr)
    print(f"  Transport:   {args.transport}", file=sys.stderr)
    print(f"  Proxy port:  http://localhost:{args.port}", file=sys.stderr)
    print(f"  Discovered:  {_proxy.tool_count} tools", file=sys.stderr)
    print(f"  Auth:        {'API key required' if PROXY_API_KEY else 'OPEN (set MORPHEUS_PROXY_KEY)'}", file=sys.stderr)

    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
