from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=False)

AUTH0_ISSUER = f"https://{settings.AUTH0_DOMAIN}/"
AUTH0_JWKS_URL = f"{AUTH0_ISSUER}.well-known/jwks.json" # this endpoint contains auth0 public keys

jwks_client = PyJWKClient(AUTH0_JWKS_URL) # this helper downloads , caches and selects correct Auth0 public keys automatically


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


async def verify_auth0_token(
    access_token: str = Depends(get_bearer_token),
) -> dict[str, Any]:
    """
    Verify Auth0 JWT access token and return decoded payload.
    """

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(
            access_token
        ).key

        payload = jwt.decode(
            access_token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.AUTH0_AUDIENCE,
            issuer=AUTH0_ISSUER,
        )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )