"""FastAPI ASGI middleware that auto-validates incoming requests via Morpheus.

Usage:
    from sdk.adapters import MorpheusMiddleware

    app = FastAPI()
    app.add_middleware(MorpheusMiddleware, morpheus_url="http://localhost:8000", protected_routes=["/api/query"])
"""

from __future__ import annotations

import json
from typing import Callable, Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from sdk.client import MorpheusClient


class MorpheusMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that validates incoming requests via Morpheus.

    On each request to a protected route:
      1. Extracts query/intent from the request body
      2. Validates via Morpheus parse endpoint
      3. If validation fails or confidence is too low, blocks the request
      4. Otherwise, proceeds to the next handler
    """

    def __init__(
        self,
        app,
        morpheus_url: str = "http://localhost:8000",
        protected_routes: Sequence[str] = (),
        domain: str = "generic_bi",
        query_field: str = "query",
    ) -> None:
        super().__init__(app)
        self._client = MorpheusClient(base_url=morpheus_url)
        self._protected = set(protected_routes)
        self._domain = domain
        self._query_field = query_field

    async def dispatch(self, request: Request, call_next: Callable):
        # Only intercept protected routes
        if request.url.path not in self._protected:
            return await call_next(request)

        # Only intercept POST requests with a body
        if request.method != "POST":
            return await call_next(request)

        try:
            body = await request.body()
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return await call_next(request)

        query = data.get(self._query_field)
        if not query:
            return await call_next(request)

        try:
            result = self._client.parse(query, domain=self._domain)
        except Exception as e:
            return JSONResponse(
                status_code=502,
                content={"error": "Morpheus validation failed", "detail": str(e)},
            )

        if not result.valid:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "Request blocked by Morpheus",
                    "validation_errors": result.errors,
                    "low_confidence": result.low_confidence,
                },
            )

        return await call_next(request)
