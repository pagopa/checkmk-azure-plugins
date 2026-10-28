"""Errors shared by Azure transports and credential providers."""

from typing import Any


class AzureError(Exception):
    """Azure failure with optional HTTP status, Azure code and response details."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details
