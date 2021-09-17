from datetime import timedelta
from uuid import UUID

from app.models.stats import StatType
from app.pg.pg_utils import get_postgres
from app.pg.queries import (
    stats_clear,
    stats_earliest,
    stats_insert,
)


async def clear_stats():
    postgres = await get_postgres()
    async with postgres.pool.acquire() as conn:
        await stats_clear(conn)


async def seed_stats(noderef_id: UUID, size: int = 10):
    postgres = await get_postgres()
    async with postgres.pool.acquire() as conn:
        portal_tree = await stats_earliest(
            conn, stat_type=StatType.PORTAL_TREE, noderef_id=noderef_id
        )
        material_types = await stats_earliest(
            conn, stat_type=StatType.MATERIAL_TYPES, noderef_id=noderef_id
        )
        validation_collections = await stats_earliest(
            conn, stat_type=StatType.VALIDATION_COLLECTIONS, noderef_id=noderef_id
        )
        validation_materials = await stats_earliest(
            conn, stat_type=StatType.VALIDATION_MATERIALS, noderef_id=noderef_id
        )

        # TODO: refactor algorithm
        # for days in range(1, size + 1):
        #     row = await stats_insert(
        #         conn,
        #         noderef_id=noderef_id,
        #         stats=row["stats"],
        #         derived_at=row["derived_at"] - timedelta(days=days),
        #     )
