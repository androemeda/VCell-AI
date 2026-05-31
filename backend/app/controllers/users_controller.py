from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.logger import get_logger
from app.core.singleton import get_supabase_client
from app.services.litellm_service import get_or_create_virtual_key

logger = get_logger("users_controller")


async def sync_current_user_controller(
    payload: dict,
) -> dict:
    """
    Sync authenticated Auth0 user into Supabase.
    """

    auth0_sub = payload.get("sub")

    if not auth0_sub:
        raise HTTPException(
            status_code=400,
            detail="Missing Auth0 subject claim",
        )

    supabase = get_supabase_client()
    email = payload.get("email")

    user_values = {
        "auth0_sub": auth0_sub,
        "last_login": datetime.now(timezone.utc).isoformat(),
    }
    if email is not None:
        user_values["email"] = email
    if payload.get("name") is not None:
        user_values["name"] = payload.get("name")

    response = (
        supabase.table("users")
        .upsert(
            user_values,
            on_conflict="auth0_sub",
        )
        .execute()
    )

    existing_key = None
    if response.data:
        existing_key = response.data[0].get("litellm_virtual_key")

    virtual_key_status = {
        "available": bool(existing_key),
        "provisioned": False,
    }

    try:
        virtual_key = await get_or_create_virtual_key(
            auth0_sub=auth0_sub,
            email=email or "",
            supabase=supabase,
        )
        virtual_key_status = {
            "available": bool(virtual_key),
            "provisioned": not bool(existing_key),
        }
    except Exception as exc:
        logger.error(f"LiteLLM provisioning failed for {auth0_sub}: {exc}")

    return {
        "status": "success",
        "user": response.data[0] if response.data else None,
        "litellm_virtual_key": virtual_key_status,
    }
