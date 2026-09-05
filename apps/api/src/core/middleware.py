"""Pure ASGI HTTP Middleware for request tracing, security headers, and rate limiting."""

import time
import uuid
import json
import logging
from collections import defaultdict
from typing import Dict, Tuple

from .config import settings
from packages.shared.src.constants import ErrorCode

logger = logging.getLogger("relationship_os.http")


class InMemoryRateLimiter:
    """Sliding window rate limiter for IP and user identifiers."""
    def __init__(self):
        self.requests: Dict[str, list] = defaultdict(list)

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: int = 60) -> Tuple[bool, int]:
        now = time.time()
        window_start = now - window_seconds
        self.requests[key] = [ts for ts in self.requests[key] if ts > window_start]
        if len(self.requests[key]) >= max_requests:
            retry_after = int(window_seconds - (now - self.requests[key][0]))
            return True, max(1, retry_after)
        self.requests[key].append(now)
        return False, 0


rate_limiter = InMemoryRateLimiter()


class RequestContextAndSecurityHeadersMiddleware:
    """Pure ASGI middleware adding X-Request-ID, security headers, and structured access logging."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode("latin1") or str(uuid.uuid4())
        
        # Store in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                resp_headers = list(message.get("headers", []))
                resp_headers.append((b"x-request-id", request_id.encode("latin1")))
                resp_headers.append((b"x-content-type-options", b"nosniff"))
                resp_headers.append((b"x-frame-options", b"DENY"))
                resp_headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                resp_headers.append((b"permissions-policy", b"camera=(), microphone=(), geolocation=()"))
                resp_headers.append((b"content-security-policy", b"default-src 'self'; frame-ancestors 'none';"))
                if settings.ENVIRONMENT == "production":
                    resp_headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = resp_headers

                duration_ms = (time.time() - start_time) * 1000
                logger.info(
                    "HTTP %s %s status=%s %.2fms [req=%s]",
                    scope.get("method"),
                    scope.get("path"),
                    message.get("status"),
                    duration_ms,
                    request_id,
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    """Pure ASGI rate limiting middleware for sensitive endpoints."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        # Rate limit login endpoint
        if path.startswith("/api/v1/auth/login") and method == "POST":
            limited, retry_after = rate_limiter.is_rate_limited(
                f"login:{client_ip}",
                max_requests=settings.RATE_LIMIT_LOGIN_PER_MINUTE,
                window_seconds=60,
            )
            if limited:
                req_id = scope.get("state", {}).get("request_id", str(uuid.uuid4()))
                body = json.dumps({
                    "error": {
                        "code": ErrorCode.RATE_LIMITED.value,
                        "message": f"Too many login attempts. Please wait {retry_after} seconds.",
                        "request_id": req_id,
                    }
                }).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry_after).encode("ascii")),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
                return

        await self.app(scope, receive, send)
