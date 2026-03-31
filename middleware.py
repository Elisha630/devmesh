"""
DevMesh Middleware Module
-------------------------
HTTP middleware for CORS, security headers, and request validation.
"""

__all__ = [
    "SecurityHeadersMiddleware",
    "CORSConfig",
    "add_security_headers",
    "create_cors_handler",
]

import orjson
from typing import Optional, Set, Callable, Dict, Any
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler


@dataclass
class CORSConfig:
    """CORS configuration."""
    allow_origins: Set[str] = None
    allow_methods: Set[str] = None
    allow_headers: Set[str] = None
    allow_credentials: bool = False
    max_age: int = 86400  # 24 hours

    def __post_init__(self):
        if self.allow_origins is None:
            self.allow_origins = {"http://localhost:7701", "http://127.0.0.1:7701"}
        if self.allow_methods is None:
            self.allow_methods = {"GET", "POST", "OPTIONS", "PUT", "DELETE"}
        if self.allow_headers is None:
            self.allow_headers = {
                "Content-Type",
                "Authorization",
                "X-Request-ID",
                "X-Client-Version",
            }


class SecurityHeadersMiddleware:
    """Middleware to add security headers to HTTP responses."""

    SECURITY_HEADERS = {
        # Prevent MIME type sniffing
        "X-Content-Type-Options": "nosniff",
        # Prevent clickjacking
        "X-Frame-Options": "DENY",
        # XSS protection (legacy browsers)
        "X-XSS-Protection": "1; mode=block",
        # Referrer policy
        "Referrer-Policy": "strict-origin-when-cross-origin",
        # Content Security Policy
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' ws://localhost:* ws://127.0.0.1:*; "
            "img-src 'self' data:; "
        ),
        # Permissions policy
        "Permissions-Policy": (
            "camera=(), microphone=(), geolocation=(), "
            "payment=(), usb=(), magnetometer=(), "
            "gyroscope=(), accelerometer=()"
        ),
    }

    def __init__(self, cors_config: Optional[CORSConfig] = None):
        self.cors_config = cors_config or CORSConfig()

    def add_headers(self, handler: BaseHTTPRequestHandler) -> None:
        """Add security headers to response."""
        for header, value in self.SECURITY_HEADERS.items():
            handler.send_header(header, value)

    def handle_cors(self, handler: BaseHTTPRequestHandler) -> bool:
        """
        Handle CORS preflight and add CORS headers.
        Returns True if this was a preflight request.
        """
        origin = handler.headers.get("Origin", "")

        # Check if origin is allowed
        allowed_origins = self.cors_config.allow_origins
        if "*" in allowed_origins or origin in allowed_origins:
            handler.send_header("Access-Control-Allow-Origin", origin or "*")

        if self.cors_config.allow_credentials:
            handler.send_header("Access-Control-Allow-Credentials", "true")

        # Handle preflight request
        if handler.command == "OPTIONS":
            handler.send_header(
                "Access-Control-Allow-Methods",
                ", ".join(self.cors_config.allow_methods)
            )
            handler.send_header(
                "Access-Control-Allow-Headers",
                ", ".join(self.cors_config.allow_headers)
            )
            handler.send_header(
                "Access-Control-Max-Age",
                str(self.cors_config.max_age)
            )
            return True

        return False


def add_security_headers(func: Callable) -> Callable:
    """Decorator to add security headers to handler methods."""
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        return result
    return wrapper


def create_cors_handler(allowed_origins: Optional[Set[str]] = None) -> Callable:
    """
    Create a CORS handler function for WebSocket connections.

    Args:
        allowed_origins: Set of allowed origins for WebSocket connections

    Returns:
        Function that checks if an origin is allowed
    """
    origins = allowed_origins or {"http://localhost:7701", "http://127.0.0.1:7701"}

    def check_origin(origin: str) -> bool:
        """Check if origin is allowed."""
        if "*" in origins:
            return True
        return origin in origins

    return check_origin


class RequestValidator:
    """Validates incoming HTTP requests."""

    # Maximum request sizes
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
    MAX_HEADER_COUNT = 100
    MAX_HEADER_SIZE = 8192  # 8KB per header

    @classmethod
    def validate_request(cls, handler: BaseHTTPRequestHandler) -> tuple[bool, Optional[str]]:
        """
        Validate an incoming request.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check content length
        content_length = handler.headers.get("Content-Length")
        if content_length:
            try:
                length = int(content_length)
                if length > cls.MAX_CONTENT_LENGTH:
                    return False, f"Content too large (max {cls.MAX_CONTENT_LENGTH} bytes)"
            except ValueError:
                return False, "Invalid Content-Length header"

        # Check header count
        if len(handler.headers) > cls.MAX_HEADER_COUNT:
            return False, "Too many headers"

        # Check for suspicious headers
        for header, value in handler.headers.items():
            if len(str(value)) > cls.MAX_HEADER_SIZE:
                return False, f"Header too large: {header}"

        return True, None

    @classmethod
    def validate_json_body(cls, body: bytes) -> tuple[bool, Optional[dict], Optional[str]]:
        """
        Validate JSON request body.

        Returns:
            Tuple of (is_valid, parsed_data, error_message)
        """
        if len(body) > cls.MAX_CONTENT_LENGTH:
            return False, None, f"Body too large (max {cls.MAX_CONTENT_LENGTH} bytes)"

        try:
            data = orjson.loads(body)
            if not isinstance(data, dict):
                return False, None, "JSON body must be an object"
            return True, data, None
        except orjson.JSONDecodeError as e:
            return False, None, f"Invalid JSON: {e}"
