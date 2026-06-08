from fastapi import Header, HTTPException

from app.core.config import get_settings


async def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    settings = get_settings()
    expected = settings.effective_internal_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API token is not configured.")
    if x_internal_token != expected:
        raise HTTPException(status_code=403, detail="Invalid internal token.")
