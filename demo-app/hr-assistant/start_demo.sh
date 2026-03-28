#!/bin/bash
# HR Assistant Demo — Full Stack
# Starts all 3 components: HR MCP server + Morpheus backend + HR chatbot app
#
# Usage:
#   cd demo-app/hr-assistant
#   chmod +x start_demo.sh
#   ./start_demo.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MORPHEUS_DIR="$SCRIPT_DIR/../../morpheus"

echo "═══════════════════════════════════════════════════════"
echo "  Morpheus HR Assistant Demo"
echo "═══════════════════════════════════════════════════════"
echo ""

# Kill any existing processes on our ports
for port in 5010 5020 8000 9000; do
    pid=$(lsof -t -i:$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "Killing existing process on port $port (PID $pid)"
        kill $pid 2>/dev/null || true
        sleep 1
    fi
done

echo ""
echo "Starting 4 services..."
echo ""

# 1. HR MCP Tool Server (the "company's real tools")
echo "[1/4] HR MCP Tool Server → port 5010"
cd "$SCRIPT_DIR"
python hr_mcp_server.py &
PID_MCP=$!
sleep 1

# 2. Morpheus Backend (Control 1 — input validation)
echo "[2/4] Morpheus Backend → port 8000"
cd "$MORPHEUS_DIR"
uvicorn main:app --port 8000 &
PID_MORPHEUS=$!
sleep 2

# 3. Morpheus HTTP Proxy (Control 2 — action validation on execution)
echo "[3/4] Morpheus HTTP Proxy → port 5020"
cd "$MORPHEUS_DIR"
python proxy/http_proxy.py --real-server http://localhost:5010 --port 5020 &
PID_PROXY=$!
sleep 1

# 4. HR Chatbot App (the company's frontend)
echo "[4/4] HR Chatbot App → port 9000"
cd "$SCRIPT_DIR"
uvicorn app:app --port 9000 &
PID_APP=$!
sleep 1

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  All services running!"
echo ""
echo "  🏢 HR Tool Server:     http://localhost:5010  (MCP tools)"
echo "  🛡️  Morpheus API:       http://localhost:8000  (Control 1)"
echo "  🔒 Morpheus Proxy:     http://localhost:5020  (Control 2)"
echo "  💬 HR Chatbot:         http://localhost:9000  (open this)"
echo ""
echo "  Flow: User → Chatbot(9000) → Morpheus(8000) → Proxy(5020) → Tools(5010)"
echo ""
echo "  Press Ctrl+C to stop all services"
echo "═══════════════════════════════════════════════════════"

# Wait for any to exit
trap "kill $PID_MCP $PID_MORPHEUS $PID_PROXY $PID_APP 2>/dev/null; exit" INT TERM
wait
