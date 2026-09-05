"""Centralized exception classes and FastAPI exception handlers."""

import logging
from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.shared.src.constants import ErrorCode

logger = logging.getLogger("relationship_os.api")


class AppException(Exception):
    """Base exception for all application errors."""
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class AuthRequiredException(AppException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code=ErrorCode.AUTH_REQUIRED,
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthInvalidException(AppException):
    def __init__(self, message: str = "Invalid credentials or token"):
        super().__init__(
            code=ErrorCode.AUTH_INVALID,
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthExpiredException(AppException):
    def __init__(self, message: str = "Authentication token expired"):
        super().__init__(
            code=ErrorCode.AUTH_EXPIRED,
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "Action not permitted for this role or identity"):
        super().__init__(
            code=ErrorCode.FORBIDDEN,
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class RateLimitedException(AppException):
    def __init__(self, message: str = "Too many requests. Please slow down."):
        super().__init__(
            code=ErrorCode.RATE_LIMITED,
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class MessageDuplicateException(AppException):
    def __init__(self, message: str = "Message with this client_message_id has already been processed"):
        super().__init__(
            code=ErrorCode.MESSAGE_DUPLICATE,
            message=message,
            status_code=status.HTTP_409_CONFLICT,
        )


class MessageTooLargeException(AppException):
    def __init__(self, message: str = "Message body exceeds allowed limit"):
        super().__init__(
            code=ErrorCode.MESSAGE_TOO_LARGE,
            message=message,
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )


class SSRFBlockedException(AppException):
    def __init__(self, message: str = "Destination URL rejected by SSRF protection"):
        super().__init__(
            code=ErrorCode.SSRF_BLOCKED,
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.warning("AppException: [%s] %s (code=%s, req=%s)", exc.status_code, exc.message, exc.code, request_id)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code.value if hasattr(exc.code, "value") else str(exc.code),
                "message": exc.message,
                "request_id": request_id,
                "details": exc.details,
            }
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.info("Validation error on %s: %s (req=%s)", request.url.path, exc.errors(), request_id)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": ErrorCode.INVALID_REQUEST.value,
                "message": "Invalid request parameters or payload",
                "request_id": request_id,
                "details": {"errors": exc.errors()},
            }
        },
    )


async def generic_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INVALID_REQUEST
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code.value,
                "message": exc.detail or "HTTP Error",
                "request_id": request_id,
                "details": {},
            }
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error("Unhandled internal error: %s (req=%s)", str(exc), request_id, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "An internal server error occurred. Please contact administrator.",
                "request_id": request_id,
                "details": {},
            }
        },
    )
