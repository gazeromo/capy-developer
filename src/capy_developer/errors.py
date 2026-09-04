from __future__ import annotations


class DeveloperError(Exception):
    """A causal, automation-safe product failure."""

    def __init__(self, code: str, detail: str, *, data: dict | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.data = data or {}

    def result(self) -> dict:
        return {
            "schema": "capy.developer-error/v0",
            "ok": False,
            "error": {"code": self.code, "detail": self.detail, **self.data},
        }

