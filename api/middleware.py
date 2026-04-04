import uuid
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from core.rate_limiter import check_rate_limit
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add a unique request ID to each incoming request and include it in the response headers."""
    async def dispatch(self, request: Request, call_next):
        # Generate a unique request ID and store it in the request state for access in route handlers
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        # Log the incoming request with the request ID
        logger.info(f"Incoming request: {request.method} {request.url} - Request ID: {request_id}")

        # Call the next middleware or route handler
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response
    

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce rate limiting based on API keys."""
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-authenticated routes (like /docs, /openapi.json)
        if request.url.path.startswith("/tenants/") or request.url.path == "/health":
            return await call_next(request)
        
        # Check for API key in headers and enforce rate limiting        
        api_key = request.headers.get("X-API-Key")
        if api_key:
            result = await check_rate_limit(api_key)
            if not result["allowed"]:
                return JSONResponse(
                        status_code = 429,
                        content = {
                            "detail": "Rate limit exceeded", "reset_in": result["reset_in"]
                        },
                    )
            
        response = await call_next(request)
        return response
    
