from enum import Enum
from typing import (
    Callable,
    Coroutine,
    List,
)
from uuid import UUID

from fastapi import BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.sql import ClauseElement
from starlette.exceptions import HTTPException
from starlette.status import HTTP_404_NOT_FOUND

import app.crud.collection as crud_collection
from app.core.config import PORTAL_ROOT_ID
from app.models.collection import (
    Collection,
    PortalTreeNode,
)


class CollectionNotFoundException(HTTPException):
    def __init__(self, noderef_id):
        super().__init__(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Collection with id '{noderef_id}' not found",
        )


class StatsNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=HTTP_404_NOT_FOUND, detail=f"Stats not found",
        )


class OrderByDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"


class OrderByParams(BaseModel):
    column: str
    direction: OrderByDirection = OrderByDirection.ASC

    def __call__(self, query: ClauseElement):
        col = query.columns[self.column]
        if self.direction == OrderByDirection.DESC:
            query = query.order_by(col.desc())
        else:
            query = query.order_by(col.asc())
        return query


async def build_portal_tree(
    portals: List[Collection], root_noderef_id: UUID
) -> List[PortalTreeNode]:
    lut = {str(root_noderef_id): []}

    for portal in portals:
        portal_node = PortalTreeNode(
            noderef_id=portal.noderef_id, title=portal.title, children=[],
        )

        try:
            lut[str(portal.parent_id)].append(portal_node)
        except KeyError:
            lut[str(portal.parent_id)] = [portal_node]

        lut[str(portal.noderef_id)] = portal_node.children

    return lut.get(str(root_noderef_id), [])


def dispatch_portal_tasks(
    noderef_id: UUID, f: Callable[[UUID], Coroutine], background_tasks: BackgroundTasks,
):
    if str(noderef_id) == PORTAL_ROOT_ID:
        for _, v in crud_collection.PORTALS.items():
            if v["value"] == PORTAL_ROOT_ID:
                continue
            background_tasks.add_task(f, noderef_id=v["value"])
    else:
        background_tasks.add_task(f, noderef_id=noderef_id)
