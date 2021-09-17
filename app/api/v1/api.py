from fastapi import APIRouter

from .endpoints.demo import router as demo_router
from .endpoints.collections import router as collections_router
from .endpoints.stats import router as stats_router
from .endpoints.seeds import router as seeds_router


router = APIRouter()
router.include_router(demo_router)
router.include_router(collections_router)
router.include_router(stats_router)
router.include_router(seeds_router)
