from fastapi import (
    APIRouter,
    BackgroundTasks,
    Security,
)
from starlette.status import (
    HTTP_202_ACCEPTED,
    HTTP_204_NO_CONTENT,
)

import app.crud.seeds as crud_seeds
from app.api.auth import authenticated
from app.core.config import PORTAL_ROOT_ID
from app.crud.util import dispatch_portal_tasks

router = APIRouter()


@router.post(
    "/clear-stats",
    dependencies=[Security(authenticated)],
    status_code=HTTP_204_NO_CONTENT,
    tags=["Statistics"],
)
async def seed_stats():
    await crud_seeds.clear_stats()


@router.post(
    "/seed-stats",
    dependencies=[Security(authenticated)],
    status_code=HTTP_202_ACCEPTED,
    tags=["Statistics"],
)
async def seed_stats(*, background_tasks: BackgroundTasks):
    dispatch_portal_tasks(
        noderef_id=PORTAL_ROOT_ID,
        f=crud_seeds.seed_stats,
        background_tasks=background_tasks,
    )
