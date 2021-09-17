from datetime import datetime
from typing import Union
from uuid import UUID

from asyncpg import (
    Connection,
    Record,
)
from sqlalchemy import (
    select,
    text,
)

from app.models.stats import StatType
from .metadata import Stats
from .pg_utils import compile_query


async def stats_clear(conn: Connection) -> Record:
    compiled_query, params, _ = compile_query(Stats.delete().where(text("1 = 1")))
    return await conn.fetchrow(compiled_query, *params)


async def stats_latest(
    conn: Connection, stat_type: StatType, noderef_id: UUID, at: datetime = None
) -> Record:
    query = (
        Stats.select()
        .where(Stats.c.noderef_id == noderef_id)
        .where(Stats.c.stat_type == stat_type.value)
    )

    if at:
        query = query.where(Stats.c.derived_at <= at)

    query = query.order_by(Stats.c.derived_at.desc()).limit(1)

    compiled_query, params, _ = compile_query(query)
    return await conn.fetchrow(compiled_query, *params)


async def stats_earliest(
    conn: Connection, stat_type: StatType, noderef_id: UUID
) -> Record:
    query = (
        Stats.select()
        .where(Stats.c.noderef_id == noderef_id)
        .where(Stats.c.stat_type == stat_type.value)
        .order_by(Stats.c.derived_at.asc())
        .limit(1)
    )

    compiled_query, params, _ = compile_query(query)
    return await conn.fetchrow(compiled_query, *params)


async def stats_insert(
    conn: Connection,
    noderef_id: UUID,
    stat_type: StatType,
    stats: Union[list, dict],
    derived_at: datetime,
) -> Record:
    # query = (
    #     Stats.insert()
    #     .values(noderef_id=noderef_id, stats=stats, derived_at=derived_at)
    #     .returning(literal_column("*"))
    # )
    #
    # compiled_query, params, _ = compile_query(query)
    # return await conn.fetchrow(compiled_query, *params)

    # there is an issue with json round-trip in this special case which is
    # related to sqlalchemy query construction and asyncpg query execution.
    # that is why above code is commented out and the following code uses literal SQL
    return await conn.fetchrow(
        """
        INSERT INTO stats(noderef_id, stat_type, stats, derived_at)
            VALUES($1, $2, $3, $4)
            RETURNING *
        """,
        noderef_id,
        stat_type.value,
        stats,
        derived_at,
    )


# TODO: specify return type
async def stats_timeline(conn: Connection, noderef_id: UUID):
    query = (
        select(Stats.c.derived_at)
        .where(Stats.c.noderef_id == noderef_id)
        .order_by(Stats.c.derived_at.desc())
    )

    compiled_query, params, _ = compile_query(query)
    return await conn.fetch(compiled_query, *params)
