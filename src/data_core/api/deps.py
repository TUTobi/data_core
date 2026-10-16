import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from data_core.config import Settings
from data_core.services import Services


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_services(request: Request) -> Services:
    return request.app.state.services


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
AppServices = Annotated[Services, Depends(get_services)]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)  # e.g. Vercel Cron sends "Authorization: Bearer <CRON_SECRET>"


def require_role(*roles: str):
    """Dependency accepting an API key (X-API-Key or Bearer) configured for any of `roles`."""

    def check(
        request: Request,
        api_key: str | None = Security(_api_key_header),
        bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    ) -> str:
        settings: Settings = request.app.state.settings
        if settings.auth_disabled:
            return "anonymous"
        token = api_key or (bearer.credentials if bearer else None)
        if token:
            for role in roles:
                if any(hmac.compare_digest(token, key) for key in settings.keys_for(role)):
                    return role
        raise HTTPException(status_code=401, detail="Invalid or missing API key", headers={"WWW-Authenticate": "Bearer"})

    return Depends(check)
