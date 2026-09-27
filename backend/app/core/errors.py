"""API error types."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        **extra: Any,
    ):
        detail = {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            },
            **extra,
        }
        super().__init__(status_code=status_code, detail=detail)
