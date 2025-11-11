from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings with validation and defaults"""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    # App
    app_name: str = "SEO Automation Platform"
    debug: bool = Field(default=False)
    secret_key: SecretStr = Field(default="your-secret-key-change-in-production")
    
    # Auth
    admin_username: str = Field(default="Admin")
    admin_password: SecretStr = Field(default="Seo_cleverly@2025")
    session_cookie_name: str = Field(default="seo_session")
    session_max_age: int = Field(default=3600)  # 1 hour
    
    # Paths
    data_dir: Path = Field(default=Path("app/data"))
    pages_file: Path = Field(default=Path("app/data/pages.json"))
    audit_file: Path = Field(default=Path("app/data/audit_log.json"))
    
    # Security
    rate_limit_auth: str = Field(default="5/minute")
    cors_origins: list[str] = Field(default=["*"])
    
    # Logging
    log_level: str = Field(default="INFO")
    
    @property
    def data_dir_path(self) -> Path:
        """Ensure data directory exists"""
        path = self.data_dir.resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance"""
    return Settings()