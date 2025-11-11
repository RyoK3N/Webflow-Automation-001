import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Request
from jose import jwt, JWTError
from app.core.config import get_settings
from app.core.logging import logger

class SecurityManager:
    def __init__(self) -> None:
        self.cfg = get_settings()

    def create_session_token(self, username: str) -> str:
        expire = datetime.utcnow() + timedelta(seconds=self.cfg.session_max_age)
        payload = {
            "sub": username,
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            payload,
            self.cfg.secret_key.get_secret_value(),
            algorithm="HS256",
        )

    def verify_session(self, request: Request) -> Optional[str]:
        token = request.cookies.get(self.cfg.session_cookie_name)
        if not token:
            return None
        try:
            payload = jwt.decode(
                token,
                self.cfg.secret_key.get_secret_value(),
                algorithms=["HS256"],
            )
            return str(payload["sub"])
        except JWTError as exc:
            logger.warning("invalid_session_token", error=str(exc))
            return None

    def require_auth(self, request: Request) -> str:
        user = self.verify_session(request)
        if user is None:
            raise HTTPException(401, "Authentication required")
        return user


security_manager = SecurityManager()