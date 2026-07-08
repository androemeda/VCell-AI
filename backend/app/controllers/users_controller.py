from fastapi import HTTPException

from app.services.users_service import (
    MissingAuth0SubjectError,
    UserBudgetLookupError,
    get_current_user_budget,
    sync_current_user,
)


async def sync_current_user_controller(
    payload: dict,
) -> dict:
    """
    Sync authenticated Auth0 user into Supabase.
    """

    try:
        return await sync_current_user(payload)
    except MissingAuth0SubjectError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


async def get_current_user_budget_controller(payload: dict) -> dict:
    try:
        return await get_current_user_budget(payload)
    except MissingAuth0SubjectError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )
    except UserBudgetLookupError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )
