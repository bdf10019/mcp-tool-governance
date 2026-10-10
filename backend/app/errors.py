from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        recoverable: bool = False,
        next_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.next_action = next_action

    def payload(self, trace_id: str | None = None) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "recoverable": self.recoverable,
                "next_action": self.next_action,
                "trace_id": trace_id,
            }
        }

