"""
Fixed Security Manager - Resolves token verification issue
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, status
from jose import jwt, JWTError

from app.core.config import get_settings
from app.core.logging import logger


class SecurityManager:
    """Security manager with fixed cookie handling."""
    
    ALGORITHM = "HS256"
    TOKEN_TYPE = "Bearer"
    
    def __init__(self) -> None:
        """Initialize security manager."""
        self.cfg = get_settings()
        logger.info("security_manager_initialized", 
                   cookie_name=self.cfg.session_cookie_name)
    
    def create_session_token(self, username: str) -> str:
        """Create a secure JWT session token."""
        try:
            # Use UTC for all timestamps
            now = datetime.now(timezone.utc)
            expire = now + timedelta(seconds=self.cfg.session_max_age)
            
            payload = {
                "sub": username,
                "exp": expire.timestamp(),
                "iat": now.timestamp(),
                "jti": str(uuid.uuid4()),
                "type": "session",
            }
            
            token = jwt.encode(
                payload,
                self.cfg.secret_key.get_secret_value(),
                algorithm=self.ALGORITHM,
            )
            
            logger.debug("session_token_created", 
                        username=username,
                        expires_in=self.cfg.session_max_age,
                        jti=payload["jti"])
            
            return token
        
        except Exception as e:
            logger.error("token_creation_failed", 
                        username=username,
                        error=str(e),
                        exc_info=True)
            raise
    
    def verify_session(self, request: Request) -> Optional[str]:
        """
        FIXED: Verify session token from request cookies.
        """
        try:
            # Get token from cookie
            token = request.cookies.get(self.cfg.session_cookie_name)
            
            if not token:
                logger.debug("no_session_token_found", 
                           cookie_name=self.cfg.session_cookie_name,
                           available_cookies=list(request.cookies.keys()))
                return None
            
            # Decode and validate token
            try:
                payload = jwt.decode(
                    token,
                    self.cfg.secret_key.get_secret_value(),
                    algorithms=[self.ALGORITHM],
                )
                
                # Validate token type
                if payload.get("type") != "session":
                    logger.warning("invalid_token_type", 
                                 type=payload.get("type"))
                    return None
                
                # Extract username
                username = payload.get("sub")
                
                if not username:
                    logger.warning("token_missing_username")
                    return None
                
                # Manual expiration check with better error handling
                exp = payload.get("exp")
                if exp:
                    now = datetime.now(timezone.utc).timestamp()
                    if now > exp:
                        logger.debug("token_expired", 
                                   username=username,
                                   expired_at=exp,
                                   now=now)
                        return None
                
                logger.debug("session_verified", 
                           username=username,
                           jti=payload.get("jti"))
                return str(username)
            
            except JWTError as e:
                logger.warning("jwt_validation_failed", 
                             error=str(e),
                             error_type=type(e).__name__)
                return None
        
        except Exception as e:
            logger.error("session_verification_error", 
                        error=str(e),
                        exc_info=True)
            return None
    
    def require_auth(self, request: Request) -> str:
        """
        FIXED: Dependency to require authentication.
        """
        username = self.verify_session(request)
        
        if username is None:
            client_ip = request.client.host if request.client else "unknown"
            logger.warning("authentication_required", 
                          path=request.url.path,
                          ip=client_ip,
                          cookies_present=list(request.cookies.keys()))
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Please log in.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Store username in request state
        request.state.username = username
        
        return username


# Singleton instance
security_manager = SecurityManager()