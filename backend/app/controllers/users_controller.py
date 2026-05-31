from fastapi import HTTPException

from app.core.singleton import get_supabase_client


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

    response = (
        supabase.table("users")
        .upsert(
            {
                "auth0_sub": auth0_sub,
            },
            on_conflict="auth0_sub",
        )
        .execute()
    )

    return {
        "status": "success",
        "user": response.data[0] if response.data else None,
    }