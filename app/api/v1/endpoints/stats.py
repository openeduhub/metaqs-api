import json
from datetime import datetime
from typing import (
    List,
    Optional,
)
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Response,
    Security,
)
from starlette.status import (
    HTTP_200_OK,
    HTTP_202_ACCEPTED,
    HTTP_404_NOT_FOUND,
)
from starlette_context import context

import app.crud.collection as crud_collection
import app.crud.stats as crud_stats
from app.api.auth import authenticated
from app.api.util import (
    portal_id_param,
    portal_id_with_root_param,
)
from app.crud.elastic import ResourceType
from app.crud.util import StatsNotFoundException
from app.models.collection import (
    CollectionAttribute,
    CollectionMaterialsCount,
    PortalTreeNode,
)
from app.models.oeh_validation import MaterialFieldValidation
from app.models.stats import (
    CollectionValidationStats,
    MaterialValidationStats,
    StatType,
    StatsResponse,
    ValidationStatsResponse,
)
from app.pg.pg_utils import get_postgres
from app.pg.postgres import Postgres
from app.score import (
    ScoreModulator,
    ScoreWeights,
    calc_scores,
    calc_weighted_score,
)

router = APIRouter()


def at_datetime_param(
    *,
    at: Optional[datetime] = Query(
        None,
        examples={
            "latest": {"value": None},
            "filtered": {"value": datetime.now().strftime("%Y-%m-%dT%H:%M")},
        },
    ),
) -> datetime:
    return at


def score_modulator_param(
    *, score_modulator: Optional[ScoreModulator] = Query(None)
) -> ScoreModulator:
    return score_modulator


def score_weights_param(
    *, score_weights: Optional[ScoreWeights] = Query(None)
) -> ScoreWeights:
    return score_weights


@router.get(
    "/collections/{noderef_id}/stats/score",
    response_model=dict,
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def score(
    *,
    noderef_id: UUID = Depends(portal_id_param),
    score_modulator: ScoreModulator = Depends(score_modulator_param),
    score_weights: ScoreWeights = Depends(score_weights_param),
    response: Response,
):
    if not score_modulator:
        score_modulator = ScoreModulator.LINEAR
    if not score_weights:
        score_weights = ScoreWeights.UNIFORM

    collection_stats = await crud_stats.run_stats_score(
        noderef_id=noderef_id, resource_type=ResourceType.COLLECTION
    )

    collection_scores = calc_scores(
        stats=collection_stats, score_modulator=score_modulator
    )

    material_stats = await crud_stats.run_stats_score(
        noderef_id=noderef_id, resource_type=ResourceType.MATERIAL
    )

    material_scores = calc_scores(stats=material_stats, score_modulator=score_modulator)

    score_ = calc_weighted_score(
        collection_scores=collection_scores,
        material_scores=material_scores,
        score_weights=score_weights,
    )

    response.headers["X-Query-Count"] = str(len(context.get("elastic_queries", [])))
    return {
        "score": score_,
        "collections": {"total": collection_stats["total"], **collection_scores},
        "materials": {"total": material_stats["total"], **material_scores},
    }


@router.get(
    "/stats/search/material-type",
    response_model=dict,
    status_code=HTTP_200_OK,
    tags=["Statistics"],
)
async def search_hits_by_material_type(
    *, query_str: str = Query(..., min_length=3, max_length=50), response: Response
):
    search_stats = await crud_stats.search_hits_by_material_type(query_str)

    response.headers["X-Query-Count"] = str(len(context.get("elastic_queries")))
    return search_stats


@router.get(
    "/stats/{noderef_id}/material-type",
    response_model=dict,
    status_code=HTTP_200_OK,
    tags=["Statistics"],
)
async def material_counts_by_type(
    *, noderef_id: UUID = Depends(portal_id_param), response: Response,
):
    material_counts = await crud_stats.material_counts_by_type(
        root_noderef_id=noderef_id
    )

    response.headers["X-Total-Count"] = str(len(material_counts))
    response.headers["X-Query-Count"] = str(len(context.get("elastic_queries")))
    return material_counts


@router.get(
    "/collections/{noderef_id}/stats/descendant-collections-materials-counts",
    response_model=List[CollectionMaterialsCount],
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def material_counts_tree(
    *, noderef_id: UUID = Depends(portal_id_with_root_param), response: Response,
):
    descendant_collections = await crud_collection.get_many(
        ancestor_id=noderef_id,
        source_fields={
            CollectionAttribute.NODEREF_ID,
            CollectionAttribute.PATH,
            CollectionAttribute.TITLE,
        },
    )
    materials_counts = await crud_collection.material_counts_by_descendant(
        ancestor_id=noderef_id,
    )

    descendant_collections = {
        collection.noderef_id: collection.title for collection in descendant_collections
    }
    stats = []
    errors = []
    for record in materials_counts.results:
        try:
            title = descendant_collections.pop(record.noderef_id)
        except KeyError:
            errors.append(record.noderef_id)
            continue

        stats.append(
            CollectionMaterialsCount(
                noderef_id=record.noderef_id,
                title=title,
                materials_count=record.materials_count,
            )
        )

    stats = [
        *[
            CollectionMaterialsCount(
                noderef_id=noderef_id, title=title, materials_count=0,
            )
            for (noderef_id, title) in descendant_collections.items()
        ],
        *stats,
    ]

    response.headers["X-Total-Count"] = str(len(stats))
    response.headers["X-Query-Count"] = str(len(context.get("elastic_queries")))
    # response.headers["X-Total-Errors"] = str(len(errors))
    return stats


async def _read_stats(
    postgres: Postgres, stat_type: StatType, noderef_id: UUID, at: datetime = None
) -> dict:
    async with postgres.pool.acquire() as conn:
        row = await crud_stats.read_stats(
            conn=conn, stat_type=stat_type, noderef_id=noderef_id, at=at
        )

    # if not row:
    #     row = await crud_stats.read_stats_file(
    #         noderef_id=noderef_id, stat_type=stat_type
    #     )

    return row


@router.get(
    "/read-stats/{noderef_id}",
    response_model=StatsResponse,
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def read_stats(
    *,
    noderef_id: UUID = Depends(portal_id_param),
    at: Optional[datetime] = Depends(at_datetime_param),
    postgres: Postgres = Depends(get_postgres),
):
    row = await _read_stats(
        postgres, stat_type=StatType.MATERIAL_TYPES, noderef_id=noderef_id, at=at
    )

    if not row:
        raise StatsNotFoundException

    if not isinstance(row["stats"], dict):
        row["stats"] = json.loads(row["stats"])

    return StatsResponse(derived_at=row["derived_at"], stats=row["stats"])


@router.get(
    "/read-stats/{noderef_id}/validation",
    response_model=List[ValidationStatsResponse[MaterialValidationStats]],
    response_model_exclude_unset=True,
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def read_stats_validation(
    *,
    noderef_id: UUID = Depends(portal_id_param),
    at: Optional[datetime] = Depends(at_datetime_param),
    postgres: Postgres = Depends(get_postgres),
):
    row = await _read_stats(
        postgres, stat_type=StatType.VALIDATION_MATERIALS, noderef_id=noderef_id, at=at
    )

    if not row:
        raise StatsNotFoundException

    if not isinstance(row["stats"], list):
        row["stats"] = json.loads(row["stats"])

    response = [
        ValidationStatsResponse[MaterialValidationStats](
            noderef_id=stat["noderef_id"],
            validation_stats=MaterialValidationStats(
                title=MaterialFieldValidation(missing=stat["missing_title"]),
                keywords=MaterialFieldValidation(missing=stat["missing_keywords"]),
                subjects=MaterialFieldValidation(missing=stat["missing_subjects"]),
                description=MaterialFieldValidation(
                    missing=stat["missing_description"]
                ),
                license=MaterialFieldValidation(missing=stat["missing_license"]),
                educontext=MaterialFieldValidation(missing=stat["missing_educontext"]),
                ads_qualifier=MaterialFieldValidation(
                    missing=stat["missing_ads_qualifier"]
                ),
                material_type=MaterialFieldValidation(
                    missing=stat["missing_material_type"]
                ),
                object_type=MaterialFieldValidation(
                    missing=stat["missing_object_type"]
                ),
            ),
        )
        for stat in row["stats"]
    ]

    return response


@router.get(
    "/read-stats/{noderef_id}/validation/collections",
    response_model=List[ValidationStatsResponse[CollectionValidationStats]],
    response_model_exclude_unset=True,
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def read_stats_validation_collection(
    *,
    noderef_id: UUID = Depends(portal_id_param),
    at: Optional[datetime] = Depends(at_datetime_param),
    postgres: Postgres = Depends(get_postgres),
):
    row = await _read_stats(
        postgres,
        stat_type=StatType.VALIDATION_COLLECTIONS,
        noderef_id=noderef_id,
        at=at,
    )

    if not row:
        raise StatsNotFoundException

    if not isinstance(row["stats"], list):
        row["stats"] = json.loads(row["stats"])

    response = [
        ValidationStatsResponse[CollectionValidationStats](
            noderef_id=stat["noderef_id"],
            validation_stats=CollectionValidationStats(
                title=stat["title"],
                keywords=stat["keywords"],
                description=stat["description"],
                educontext=stat["educontext"],
            ),
        )
        for stat in row["stats"]
    ]

    return response


@router.get(
    "/read-stats/{noderef_id}/portal-tree",
    response_model=List[PortalTreeNode],
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def read_stats_portal_tree(
    *,
    noderef_id: UUID = Depends(portal_id_param),
    at: Optional[datetime] = Depends(at_datetime_param),
    postgres: Postgres = Depends(get_postgres),
):
    row = await _read_stats(
        postgres, stat_type=StatType.PORTAL_TREE, noderef_id=noderef_id, at=at
    )

    if not row:
        raise StatsNotFoundException

    if not isinstance(row["stats"], list):
        row["stats"] = json.loads(row["stats"])

    response = [PortalTreeNode.construct(**node) for node in row["stats"]]

    return response


@router.get(
    "/read-stats/{noderef_id}/timeline",
    response_model=List[datetime],
    status_code=HTTP_200_OK,
    responses={HTTP_404_NOT_FOUND: {"description": "Collection not found"}},
    tags=["Statistics"],
)
async def read_stats_timeline(
    *,
    noderef_id: UUID = Depends(portal_id_param),
    postgres: Postgres = Depends(get_postgres),
):
    async with postgres.pool.acquire() as conn:
        return await crud_stats.read_stats_timeline(conn=conn, noderef_id=noderef_id)


@router.post(
    "/run-stats",
    dependencies=[Security(authenticated)],
    status_code=HTTP_202_ACCEPTED,
    tags=["Statistics", "Authenticated"],
)
async def run_stats(*, background_tasks: BackgroundTasks):
    portals = await crud_collection.get_portals()
    for portal_id in portals.keys():
        background_tasks.add_task(crud_stats.run_stats, noderef_id=portal_id)
