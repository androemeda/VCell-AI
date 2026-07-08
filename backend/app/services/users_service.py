from datetime import datetime, timezone

from app.core.logger import get_logger
from app.core.singleton import get_supabase_client
from app.services.litellm_service import (
    get_or_create_virtual_key,
    get_user_budget_info,
)

logger = get_logger("users_service")


class MissingAuth0SubjectError(ValueError):
    pass


class UserBudgetLookupError(RuntimeError):
    pass


def _get_auth0_sub(payload: dict) -> str:
    auth0_sub = payload.get("sub")
    if not auth0_sub:
        raise MissingAuth0SubjectError("Missing Auth0 subject claim")
    return auth0_sub


def sync_auth0_user(payload: dict) -> dict | None:
    """
    Create or update the local Supabase user row from verified Auth0 claims.
    """
    auth0_sub = _get_auth0_sub(payload)
    email = payload.get("email")

    user_values = {
        "auth0_sub": auth0_sub,
        "last_login": datetime.now(timezone.utc).isoformat(),
    }
    if email is not None:
        user_values["email"] = email
    if payload.get("name") is not None:
        user_values["name"] = payload.get("name")

    supabase = get_supabase_client()

    # AuthSync can run more than once during client hydration; upsert keeps this idempotent.
    response = (
        supabase.table("users")
        .upsert(
            user_values,
            on_conflict="auth0_sub",
        )
        .execute()
    )

    return response.data[0] if response.data else None


async def sync_current_user(payload: dict) -> dict:
    """
    Sync the Auth0 user locally and ensure a LiteLLM virtual key exists.
    """
    auth0_sub = _get_auth0_sub(payload)
    user = sync_auth0_user(payload)
    existing_key = user.get("litellm_virtual_key") if user else None

    virtual_key_status = {
        "available": bool(existing_key),
        "provisioned": False,
    }

    try:
        virtual_key = await get_or_create_virtual_key(
            auth0_sub=auth0_sub,
            email=payload.get("email") or "",
            supabase=get_supabase_client(),
        )
        virtual_key_status = {
            "available": bool(virtual_key),
            "provisioned": not bool(existing_key),
        }
    except Exception as exc:
        logger.error(f"LiteLLM provisioning failed for {auth0_sub}: {exc}")

    return {
        "status": "success",
        "user": user,
        "litellm_virtual_key": virtual_key_status,
    }


async def get_current_user_budget(payload: dict) -> dict:
    auth0_sub = _get_auth0_sub(payload)

    try:
        return await get_user_budget_info(auth0_sub)
    except Exception as exc:
        logger.error(f"LiteLLM budget lookup failed for {auth0_sub}: {exc}")
        raise UserBudgetLookupError("Unable to retrieve budget from LiteLLM") from exc
