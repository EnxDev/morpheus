"""Minimal example: parse -> validate -> decide.

Requires: backend running (uvicorn main:app --port 8000) + Ollama with mistral model.

Run from project root:
    python docs/examples/basic_pipeline.py
"""

import sys
from pathlib import Path

# Add morpheus to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "morpheus"))

from sdk import MorpheusClient

client = MorpheusClient()

# Step 1: Parse a query
result = client.parse("Show me revenue by region for Q1 2025")
print("Parsed intent:")
for field, hypotheses in result.intent.items():
    if hypotheses:
        top = hypotheses[0]
        print(f"  {field}: {top['value']} (confidence: {top['confidence']})")

print(f"\nLow confidence fields: {result.low_confidence}")
print(f"Valid: {result.valid}")

# Step 2: Clarify if needed
intent = result.intent
for field in result.low_confidence:
    answer = input(f"\nPlease clarify '{field}': ")
    clarified = client.clarify(intent, field, answer)
    intent = clarified.intent
    if not clarified.low_confidence:
        break

# Step 3: Decide on action
decision = client.decide(intent)
print(f"\nAction: {decision.action}")
print(f"Score: {decision.score}")
print(f"Explained: {decision.explained}")
