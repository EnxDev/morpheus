"""Use the Morpheus SDK middleware in an existing FastAPI app.

Requires: Morpheus backend running (uvicorn main:app --port 8000).

Run from project root:
    cd morpheus && uvicorn docs.examples.fastapi_integration:app --port 9000

Or simply:
    pip install fastapi uvicorn
    python docs/examples/fastapi_integration.py
"""

import sys
from pathlib import Path

# Add morpheus to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "morpheus"))

from fastapi import FastAPI
from sdk.adapters import MorpheusMiddleware

app = FastAPI(title="My Protected App")

# Add Morpheus middleware to auto-validate requests
app.add_middleware(
    MorpheusMiddleware,
    morpheus_url="http://localhost:8000",
    protected_routes=["/api/query"],
    domain="generic_bi",
    query_field="query",
)


@app.post("/api/query")
async def handle_query(data: dict):
    """This endpoint is protected by Morpheus.

    If the query fails validation, Morpheus returns a 422 before this handler runs.
    """
    return {
        "message": f"Query validated and accepted: {data.get('query', '')}",
        "result": "Processing...",
    }


@app.get("/api/public")
async def public_endpoint():
    """This endpoint is NOT protected (not in protected_routes)."""
    return {"message": "This endpoint has no Morpheus validation"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
