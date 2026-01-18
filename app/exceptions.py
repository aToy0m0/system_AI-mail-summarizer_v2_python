"""Custom exceptions for the application."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base exception for application errors."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class AuthenticationError(AppError):
    """Raised when authentication fails."""

    pass


class AuthorizationError(AppError):
    """Raised when user lacks required permissions."""

    pass


class NotFoundError(AppError):
    """Raised when a resource is not found."""

    pass


class ValidationError(AppError):
    """Raised when input validation fails."""

    pass


class ExternalServiceError(AppError):
    """Base exception for external service errors."""

    def __init__(
        self,
        message: str,
        service_name: str,
        base_url: str | None = None,
        hint: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, detail)
        self.service_name = service_name
        self.base_url = base_url
        self.hint = hint


class DifyConnectionError(ExternalServiceError):
    """Raised when Dify connection fails."""

    def __init__(
        self,
        message: str = "Dify connection failed",
        base_url: str | None = None,
        hint: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, "Dify", base_url, hint, detail)


class PleasanterConnectionError(ExternalServiceError):
    """Raised when Pleasanter connection fails."""

    def __init__(
        self,
        message: str = "Pleasanter API error",
        base_url: str | None = None,
        hint: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, "Pleasanter", base_url, hint, detail)


class ConfigurationError(AppError):
    """Raised when required configuration is missing."""

    pass
