"""
Enhanced Application Configuration with Validation
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with comprehensive validation and defaults.
    
    All settings can be overridden via environment variables.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )
    
    # Application Settings
    app_name: str = Field(
        default="SEO Automation Platform",
        description="Application name displayed in UI"
    )
    
    debug: bool = Field(
        default=False,
        description="Enable debug mode (DO NOT use in production)"
    )
    
    secret_key: SecretStr = Field(
        default=SecretStr("your-secret-key-change-in-production"),
        description="Secret key for JWT signing (must be changed in production)"
    )
    
    # Authentication Settings
    admin_username: str = Field(
        default="Admin",
        min_length=3,
        max_length=50,
        description="Administrator username"
    )
    
    admin_password: SecretStr = Field(
        default=SecretStr("Seo_cleverly@2025"),
        description="Administrator password"
    )
    
    session_cookie_name: str = Field(
        default="seo_session",
        description="Name of the session cookie"
    )
    
    session_max_age: int = Field(
        default=3600,
        ge=300,  # Minimum 5 minutes
        le=86400,  # Maximum 24 hours
        description="Session timeout in seconds"
    )
    
    # Path Settings
    data_dir: Path = Field(
        default=Path("app/data"),
        description="Directory for data storage"
    )
    
    pages_file: Path = Field(
        default=Path("app/data/pages.json"),
        description="Path to pages JSON file"
    )
    
    audit_file: Path = Field(
        default=Path("app/data/audit_log.json"),
        description="Path to audit log JSON file"
    )
    
    # Security Settings
    rate_limit_auth: str = Field(
        default="5/minute",
        description="Rate limit for authentication endpoints"
    )
    
    cors_origins: List[str] = Field(
        default=["*"],
        description="Allowed CORS origins"
    )
    
    # Logging Settings
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    
    # Validation
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of {valid_levels}"
            )
        return v_upper
    
    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: SecretStr) -> SecretStr:
        """Validate secret key has sufficient length."""
        secret_value = v.get_secret_value()
        if len(secret_value) < 32:
            raise ValueError(
                "Secret key must be at least 32 characters long"
            )
        return v
    
    @property
    def data_dir_path(self) -> Path:
        """
        Ensure data directory exists and return resolved path.
        
        Returns:
            Resolved Path object for data directory
        """
        path = self.data_dir.resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return not self.debug
    
    def get_database_url(self) -> str:
        """
        Get database URL (placeholder for future database integration).
        
        Returns:
            Database connection URL
        """
        # Placeholder for future database support
        return "sqlite:///./app/data/seo_automation.db"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance (singleton pattern).
    
    Returns:
        Settings instance
    """
    return Settings()