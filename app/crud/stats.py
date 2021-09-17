# import asyncio
import json
from collections import defaultdict
from datetime import datetime
from pprint import pformat
from typing import List, Union
from uuid import UUID

from aiofiles import open
from aiofiles.os import mkdir
from asyncpg import (
    Connection,
    Record,
)
from elasticsearch_dsl.response import Response
from fastapi import HTTPException
from glom import (
    glom,
    merge,
    Iter,
)

import app.crud.collection as crud_collection
from app.core.config import (
    DATA_DIR,
    DEBUG,
)

# from app.core.util import slugify
from app.elastic import Search
from app.elastic.utils import (
    merge_agg_response,
    merge_composite_agg_response,
)
from app.models.stats import StatType
from app.pg.pg_utils import get_postgres
from app.pg.queries import (
    stats_insert,
    stats_latest,
    stats_timeline,
)
from app.core.logging import logger
from .elastic import (
    agg_collection_validation,
    agg_materials_by_collection,
    agg_material_types,
    agg_material_types_by_collection,
    agg_material_validation,
    parse_agg_collection_validation_response,
    parse_agg_material_validation_response,
    query_collections,
    query_materials,
    runtime_mappings_collection_validation,
    search_materials,
)
from .util import build_portal_tree


async def material_types() -> List[str]:
    s = Search().query(query_materials())
    s.aggs.bucket("material_types", agg_material_types())

    response: Response = s[:0].execute()

    if response.success():
        # TODO: refactor algorithm
        return glom(
            response.aggregations.material_types.buckets,
            # (Iter("key").map(lambda k: {slugify(k): k}).all(), merge,),
            Iter("key").all(),
        )


# async def material_types_lut() -> dict:
#     mt = await get_material_types()
#     return {v: k for k, v in mt.items()}


async def material_counts_by_type(root_noderef_id: UUID) -> dict:
    s = Search().query(query_materials(ancestor_id=root_noderef_id))
    s.aggs.bucket("material_types", agg_material_types_by_collection())
    s.aggs.bucket("totals", agg_materials_by_collection())

    response: Response = s[:0].execute()

    if response.success():
        # lut = await material_types_lut()

        def fold_material_types(carry, bucket):
            # material_type = lut[stat["key"]["material_type"]]
            material_type = bucket["key"]["material_type"]
            if not material_type:
                material_type = "N/A"
            count = bucket["doc_count"]
            record = carry[bucket["key"]["noderef_id"]]
            record[material_type] = count

        # TODO: refactor algorithm
        stats = merge(
            response.aggregations.material_types.buckets,
            op=fold_material_types,
            init=lambda: defaultdict(dict),
        )

        totals = merge_composite_agg_response(
            response.aggregations.totals, key="noderef_id"
        )

        for noderef_id, counts in stats.items():
            counts["total"] = totals.get(noderef_id)

        return stats


async def search_hits_by_material_type(query_string: str) -> dict:
    s = Search().query(query_materials()).query(search_materials(query_string))
    s.aggs.bucket("material_types", agg_material_types())

    response: Response = s[:0].execute()

    if response.success():
        # lut = await material_types_lut()
        stats = merge_agg_response(response.aggregations.material_types)
        stats["total"] = sum(stats.values())
        return stats


async def run_stats_material_types(root_noderef_id: UUID) -> dict:
    portals = await crud_collection.get_many_sorted(root_noderef_id=root_noderef_id)
    material_counts = await material_counts_by_type(root_noderef_id=root_noderef_id)

    # TODO: refactor algorithm
    stats = {}
    for portal in portals:
        stats[str(portal.noderef_id)] = {
            "search": await search_hits_by_material_type(portal.title),
            "material_types": material_counts.get(str(portal.noderef_id), {}),
        }

    return stats


async def run_stats_validation_collections(root_noderef_id: UUID) -> List[dict]:
    s = (
        Search()
        .query(query_collections(ancestor_id=root_noderef_id))
        .extra(runtime_mappings=runtime_mappings_collection_validation)
    )
    s.aggs.bucket("grouped_by_collection", agg_collection_validation())

    response: Response = s[:0].execute()

    if response.success():
        return parse_agg_collection_validation_response(
            response.aggregations.grouped_by_collection
        )


async def run_stats_validation_materials(root_noderef_id: UUID) -> List[dict]:
    s = Search().query(query_materials(ancestor_id=root_noderef_id))
    s.aggs.bucket("grouped_by_collection", agg_material_validation())

    response: Response = s[:0].execute()

    if response.success():
        return parse_agg_material_validation_response(
            response.aggregations.grouped_by_collection
        )


async def run_stats(noderef_id: UUID):
    portals = await crud_collection.get_many_sorted(root_noderef_id=noderef_id)
    tree = await build_portal_tree(portals=portals, root_noderef_id=noderef_id)

    material_types_stats = await run_stats_material_types(root_noderef_id=noderef_id)

    validation_collections_stats = await run_stats_validation_collections(
        root_noderef_id=noderef_id
    )

    validation_materials_stats = await run_stats_validation_materials(
        root_noderef_id=noderef_id
    )

    derived_at = datetime.now()

    async def store_stats(t):
        postgres = await get_postgres()

        stat_type, stats = t

        async with postgres.pool.acquire() as conn:
            row = await stats_insert(
                conn,
                noderef_id=noderef_id,
                stat_type=stat_type,
                stats=stats,
                derived_at=derived_at,
            )

        # await write_stats_file(row, stat_type=stat_type)

    # TODO: encapsulate in transaction
    await store_stats(
        (StatType.PORTAL_TREE, [json.loads(node.json()) for node in tree])
    )
    await store_stats((StatType.MATERIAL_TYPES, material_types_stats))
    await store_stats((StatType.VALIDATION_COLLECTIONS, validation_collections_stats))
    await store_stats((StatType.VALIDATION_MATERIALS, validation_materials_stats))

    # results = await asyncio.gather([
    #     store_stats((StatType.PORTAL_TREE, tree)),
    #     store_stats((StatType.MATERIAL_TYPES, material_types_stats)),
    #     store_stats((StatType.VALIDATION_COLLECTIONS, validation_collections_stats[0])),
    #     store_stats((StatType.VALIDATION_MATERIALS, validation_materials_stats[0])),
    # ])


async def read_stats(
    conn: Connection, stat_type: StatType, noderef_id: UUID, at: datetime = None
) -> Union[dict, None]:
    row = await stats_latest(conn, stat_type, noderef_id, at=at)

    if row:
        if DEBUG:
            logger.debug(f"Read from postgres:\n{pformat(dict(row))}")

        return dict(row)


async def read_stats_timeline(conn: Connection, noderef_id: UUID) -> List[datetime]:
    rows = await stats_timeline(conn, noderef_id=noderef_id)

    if rows:
        return [row["derived_at"] for row in rows]


async def write_stats_file(row: Record, stat_type: StatType):
    try:
        await mkdir(DATA_DIR / stat_type.value)
    except FileExistsError:
        ...

    try:
        async with open(
            (DATA_DIR / stat_type.value) / str(row["noderef_id"]), mode="w"
        ) as f:
            await f.write(
                json.dumps(
                    {"derived_at": row["derived_at"].isoformat(), "stats": row["stats"]}
                )
            )
    except OSError:
        raise HTTPException(status_code=500)


async def read_stats_file(noderef_id: UUID, stat_type: StatType) -> Union[dict, None]:
    try:
        async with open(DATA_DIR / stat_type.value / str(noderef_id), mode="r") as f:
            content = await f.read()
    except FileNotFoundError:
        return None

    return json.loads(content)
