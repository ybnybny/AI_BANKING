"""业务异常。"""
from __future__ import annotations


class BankingError(Exception):
    """银行业务基础异常。"""

    def __init__(self, message: str, code: str = "BANKING_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(BankingError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message, "NOT_FOUND")


class InsufficientFundsError(BankingError):
    def __init__(self, message: str = "余额不足") -> None:
        super().__init__(message, "INSUFFICIENT_FUNDS")


class ConfirmationRequiredError(BankingError):
    """需要用户确认后才能执行。"""

    def __init__(self, message: str = "该操作需要用户确认") -> None:
        super().__init__(message, "CONFIRMATION_REQUIRED")


class InvalidOperationError(BankingError):
    def __init__(self, message: str = "非法操作") -> None:
        super().__init__(message, "INVALID_OPERATION")
