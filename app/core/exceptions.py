"""
Custom Exception Classes for SEO Automation Platform
Provides a hierarchy of exceptions for better error handling and debugging.
"""

from typing import Optional, Dict, Any
from fastapi import status


class AppException(Exception):
    """
    Base exception class for all application-specific exceptions.
    
    Attributes:
        message: Human-readable error message
        status_code: HTTP status code
        details: Additional error details
    """
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return f"{self.__class__.__name__}: {self.message}"
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message='{self.message}', "
            f"status_code={self.status_code}, "
            f"details={self.details})"
        )


class ValidationException(AppException):
    """
    Raised when data validation fails.
    """
    
    def __init__(
        self,
        message: str = "Validation error",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details
        )


class AuthenticationException(AppException):
    """
    Raised when authentication fails.
    """
    
    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details
        )


class AuthorizationException(AppException):
    """
    Raised when authorization fails (insufficient permissions).
    """
    
    def __init__(
        self,
        message: str = "Insufficient permissions",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            details=details
        )


class StorageException(AppException):
    """
    Raised when storage operations fail.
    """
    
    def __init__(
        self,
        message: str = "Storage operation failed",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details
        )


class CSVException(AppException):
    """
    Raised when CSV processing fails.
    """
    
    def __init__(
        self,
        message: str = "CSV processing error",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


class AuditException(AppException):
    """
    Raised when audit logging fails.
    """
    
    def __init__(
        self,
        message: str = "Audit logging error",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details
        )


class RateLimitException(AppException):
    """
    Raised when rate limit is exceeded.
    """
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details
        )