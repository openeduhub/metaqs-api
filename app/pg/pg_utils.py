import json
from pprint import pformat
from typing import Tuple

import asyncpg
from sqlalchemy.sql import ClauseElement
from sqlalchemy.dialects.postgresql import pypostgresql

from app.core.config import (
    DATABASE_URL,
    DEBUG,
    MAX_CONNECTIONS_COUNT,
    MIN_CONNECTIONS_COUNT,
)
from app.core.logging import logger
from .postgres import postgres

dialect = pypostgresql.dialect(paramstyle="pyformat")
dialect.implicit_returning = True
dialect.supports_native_enum = True
dialect.supports_smallserial = True
dialect._backslash_escapes = False
dialect.supports_sane_multi_rowcount = True
dialect._has_native_hstore = True


async def get_postgres():
    if not postgres.pool:
        await connect_to_postgres()
    return postgres


async def connect_to_postgres():
    postgres.pool = await asyncpg.create_pool(
        str(DATABASE_URL),
        min_size=MIN_CONNECTIONS_COUNT,
        max_size=MAX_CONNECTIONS_COUNT,
    )

    async with postgres.pool.acquire() as conn:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def close_postgres_connection():
    if postgres.pool:
        await postgres.pool.close()


def compile_query(query: ClauseElement) -> Tuple[str, list, tuple]:
    compiled = query.compile(dialect=dialect)
    compiled_params = sorted(compiled.params.items())

    mapping = {key: "$" + str(i) for i, (key, _) in enumerate(compiled_params, start=1)}
    compiled_query = compiled.string % mapping

    processors = compiled._bind_processors
    params = [
        processors[key](val) if key in processors else val
        for key, val in compiled_params
    ]

    if DEBUG:
        logger.debug(
            f"Compiled query to postgres:\n{pformat(compiled_query)}\nParams:\n{pformat(params)}"
        )

    return compiled_query, params, compiled._result_columns
