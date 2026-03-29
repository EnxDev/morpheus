# HR Assistant — Intent Guard Demo

A realistic HR self-service chatbot that demonstrates Intent Guard (Morpheus) integration. Employees ask questions in natural language about leave, payroll, attendance and org chart. Every request goes through the Morpheus validation pipeline before touching any data.

## Architecture

```
Employee (browser)
    │
    ▼
HR Assistant (port 9000)     ──►   Intent Guard / Morpheus (port 8000)
    │                                    │
    │  1. POST /api/chat                 │  POST /api/parse     → Control 1
    │  ◄─── clarification? ◄─────────── │  POST /api/clarify
    │  ──► answer ──────────────────────►│  POST /api/decide    → Control 2
    │                                    │
    ▼                                    ▼
Fake HR Database                    Audit Log
(in-memory Python)
```

## Quick Start

### 1. Start Morpheus (Intent Guard)

```bash
cd morpheus
pip install -r requirements.txt
uvicorn main:app --port 8000
```

### 2. Start the HR Assistant

```bash
cd morpheus-hr-chatbot-demo
pip install -r requirements.txt
uvicorn app:app --port 9000
```

### 3. Open the browser

Go to **http://localhost:9000**

## Demo Scenarios

### Happy Path (clear query)

> "How many vacation days do I have left?"

- Parse: high confidence on all fields
- No clarification
- Action: `query_leave_balance` → approved
- Result: employee leave balance

### Ambiguous Query (clarification loop)

> "How many days do I have left?"

- Parse: `hr_category` low confidence (leave? permits? sick days?)
- Morpheus asks: "Which HR category are you interested in?"
- The user responds → re-parse → execution

### Dangerous Action (Control 2 block)

> "Delete all pending leave requests"

- Parse: `action_type = delete`
- Control 2 Level 1: `delete_*` → **HIGH RISK** → blocked
- The user sees the reason for the block

## Fake Data

The app simulates an Italian company with ~12 employees:

| Department  | People  |
| ----------- | ------- |
| Engineering | 5       |
| Sales       | 4       |
| HR          | 3       |

The current user is **Enzo** (Developer, Engineering).

## Files

```
morpheus-hr-chatbot-demo/
├── app.py              # FastAPI backend + Morpheus integration
├── fake_db.py          # In-memory HR database
├── hr_domain.py        # Morpheus domain configuration
├── hr_mcp_server.py    # MCP tool server for HR actions
├── requirements.txt
├── start_demo.sh       # Script to launch all demo services
├── static/
│   ├── style.css       # Dark theme UI
│   └── chat.js         # Chat logic + pipeline visualization
└── templates/
    └── index.html      # Jinja2 template
```
