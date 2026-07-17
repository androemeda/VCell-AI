from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


def _get_auth0_config() -> tuple[str, str, PyJWKClient]:
    if not settings.AUTH0_DOMAIN or not settings.AUTH0_AUDIENCE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth0 configuration is missing",
        )

    issuer = f"https://{settings.AUTH0_DOMAIN}/"
    jwks_url = f"{issuer}.well-known/jwks.json"

    global _jwks_client
    if _jwks_client is None:
        # PyJWKClient downloads and caches Auth0 signing keys lazily,
        # so missing network access does not block app startup.
        _jwks_client = PyJWKClient(jwks_url)

    return issuer, settings.AUTH0_AUDIENCE, _jwks_client


def strip_bearer_prefix(token: str) -> str:
    """
    Return only the bearer token value, even if the input includes the
    Authorization scheme.
    """
    token = token.strip().strip('"')
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def bearer_authorization_header(token: str) -> str:
    """
    Build a standard Authorization header value from a raw bearer token.
    """
    return f"Bearer {strip_bearer_prefix(token)}"


async def get_bearer_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Extract raw bearer token from Authorization header.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


async def get_optional_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    """
    Extract raw bearer token from Authorization header if present, without
    requiring one. Lets anonymous callers through for endpoints that serve
    public data but can use a token to also surface the caller's private data.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None

    return credentials.credentials


async def verify_auth0_token(
    access_token: str = Depends(get_bearer_token),
) -> dict[str, Any]:
    """
    Verify Auth0 JWT access token and return decoded payload.
    """

    try:
        issuer, audience, jwks_client = _get_auth0_config()
        signing_key = jwks_client.get_signing_key_from_jwt(
            access_token
        ).key

        payload = jwt.decode(
            access_token,
            signing_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )

    except (jwt.InvalidTokenError, PyJWKClientError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
