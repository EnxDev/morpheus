"""Register a custom domain configuration.

Requires: backend running (uvicorn main:app).
"""

import requests

# Define a custom domain for an email system
config = {
    "name": "email",
    "domain_description": "Email management system",
    "fields": [
        {
            "name": "recipient",
            "label": "Recipient",
            "description": "Who to send the email to",
            "threshold": 0.85,
            "weight": 0.4,
            "priority": 1,
            "fallback_question": "Who should receive this email?",
            "examples": ["john@company.com", "sales team", "all managers"],
        },
        {
            "name": "subject",
            "label": "Subject",
            "description": "Email subject line",
            "threshold": 0.80,
            "weight": 0.3,
            "priority": 2,
            "fallback_question": "What is the email about?",
            "examples": ["Q1 Report", "Meeting Follow-up", "Project Update"],
        },
        {
            "name": "urgency",
            "label": "Urgency",
            "description": "How urgent is this email",
            "threshold": 0.60,
            "weight": 0.1,
            "priority": 3,
            "default_value": "normal",
            "fallback_question": "How urgent is this?",
            "examples": ["urgent", "normal", "low priority"],
        },
    ],
    "capabilities": [
        {
            "action": "send_email",
            "field_weights": {"recipient": 1.0, "subject": 0.8, "urgency": 0.2},
            "min_score": 0.6,
        },
        {
            "action": "draft_email",
            "field_weights": {"recipient": 0.5, "subject": 1.0, "urgency": 0.1},
            "min_score": 0.4,
        },
    ],
    "execution_plans": {
        "send_email": [
            {"step": "compose_email", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "send", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
        ],
        "draft_email": [
            {"step": "compose_email", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "save_draft", "type": "reversible", "timeout_ms": 2000, "retry": 1},
        ],
    },
}

# Register via API
resp = requests.post(
    "http://localhost:8000/api/domains/register",
    json={"config": config},
)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")

# List all domains
resp = requests.get("http://localhost:8000/api/domains")
print(f"\nRegistered domains: {list(resp.json().keys())}")
