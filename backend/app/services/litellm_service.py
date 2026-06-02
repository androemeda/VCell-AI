from decimal import Decimal
from typing import Any, Optional

import httpx
from supabase import Client

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("litellm_service")


def _headers() -> dict[str, str]:
    if not settings.LITELLM_MASTER_KEY:
        raise ValueError("LITELLM_MASTER_KEY is not configured")

    return {
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}",
        "Content-Type": "application/json",
    }


def _budget_value(value: Decimal) -> float:
    return float(value)


async def provision_user(auth0_sub: str, email: str) -> str:
    """
    Creates user in LiteLLM and generates a virtual key.
    Returns the virtual key string.
    Called only on first login (when litellm_virtual_key is NULL in Supabase).
    """

    if not auth0_sub:
        raise ValueError("auth0_sub is required to provision LiteLLM user")

    base_url = settings.LITELLM_URL.rstrip("/")
    user_body: dict[str, Any] = {
        "user_id": auth0_sub,
        "user_email": email,
        "max_budget": _budget_value(settings.DEFAULT_USER_BUDGET),
        "budget_duration": settings.DEFAULT_BUDGET_DURATION,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        user_already_exists = False
        user_response = await client.post(
            f"{base_url}/user/new",
            headers=_headers(),
            json=user_body,
        )
        if user_response.status_code >= 400:
            response_text = user_response.text.lower()
            if (
                user_response.status_code == 400
                and "already" in response_text
                and "exist" in response_text
            ):
                logger.info(f"LiteLLM user already exists for {auth0_sub}")
                user_already_exists = True
            else:
                user_response.raise_for_status()

        if user_already_exists:
            key_response = await client.post(
                f"{base_url}/key/generate",
                headers=_headers(),
                json={"user_id": auth0_sub},
            )
            key_response.raise_for_status()
            key_data = key_response.json()
            virtual_key = key_data.get("key")
        else:
            user_data = user_response.json()
            virtual_key = user_data.get("key")

    if not virtual_key or not virtual_key.startswith("sk-"):
        raise ValueError("LiteLLM did not return a valid virtual key for new user")

    logger.info(f"Provisioned LiteLLM virtual key for user {auth0_sub}")
    return virtual_key


def _get_existing_virtual_key(auth0_sub: str, supabase: Client) -> Optional[str]:
    response = (
        supabase.table("users")
        .select("litellm_virtual_key")
        .eq("auth0_sub", auth0_sub)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0].get("litellm_virtual_key")


async def get_or_create_virtual_key(
    auth0_sub: str,
    email: str,
    supabase: Client,
) -> str:
    """
    Checks Supabase for existing virtual key.
    If found, returns it.
    If not found, calls provision_user() and stores the key in Supabase.
    """

    existing_key = _get_existing_virtual_key(auth0_sub, supabase)
    if existing_key:
        return existing_key

    virtual_key = await provision_user(auth0_sub=auth0_sub, email=email)

    user_values = {
        "auth0_sub": auth0_sub,
        "litellm_virtual_key": virtual_key,
    }
    if email:
        user_values["email"] = email

    supabase.table("users").upsert(
        user_values,
        on_conflict="auth0_sub",
    ).execute()

    return virtual_key


async def get_user_budget_info(auth0_sub: str) -> dict:
    """
    Calls GET http://litellm:4000/user/info?user_id=auth0_sub with
    LITELLM_MASTER_KEY. Returns budget fields used by the frontend.
    """

    base_url = settings.LITELLM_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/user/info",
            headers=_headers(),
            params={"user_id": auth0_sub},
        )
        response.raise_for_status()

    data = response.json()
    user_info = data.get("user_info") if isinstance(data, dict) else None
    if isinstance(user_info, dict):
        data = user_info

    return {
        "spend": data.get("spend"),
        "max_budget": data.get("max_budget"),
        "budget_duration": data.get("budget_duration"),
        "budget_reset_at": data.get("budget_reset_at"),
    }
