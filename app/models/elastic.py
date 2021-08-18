from abc import ABC
from enum import Enum
from typing import (
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
)
from uuid import UUID

from elasticsearch_dsl.response import Response
from pydantic import (
    BaseModel as PydanticBaseModel,
    Extra,
)
from glom import (
    glom,
    Coalesce,
    Iter,
)

from .base import BaseModel
from .util import EmptyStrToNone

_ELASTIC_RESOURCE = TypeVar("_ELASTIC_RESOURCE")
_ELASTIC_AGG = TypeVar("_ELASTIC_AGG")
_BUCKET_AGG = TypeVar("_BUCKET_AGG")
_DESCENDANT_COLLECTIONS_MATERIALS_COUNTS = TypeVar(
    "_DESCENDANT_COLLECTIONS_MATERIALS_COUNTS"
)


class Attribute(str, Enum):
    NODEREF_ID = "nodeRef.id"
    TYPE = "type"
    PATH = "path"
    NAME = "properties.cm:name"


class ElasticConfig:
    allow_population_by_field_name = True
    extra = Extra.allow


class ElasticResource(BaseModel):

    noderef_id: UUID
    type: Optional[EmptyStrToNone] = None
    path: Optional[List[UUID]] = None
    name: Optional[EmptyStrToNone] = None

    class Config(ElasticConfig):
        pass

    @classmethod
    def source_fields(cls: Type[_ELASTIC_RESOURCE],) -> List:
        return [
            Attribute.NODEREF_ID,
            Attribute.TYPE,
            Attribute.PATH,
            Attribute.NAME,
        ]

    @classmethod
    def parse_elastic_hit(
        cls: Type[_ELASTIC_RESOURCE], hit: Dict,
    ) -> _ELASTIC_RESOURCE:
        return cls.construct(
            noderef_id=glom(hit, Attribute.NODEREF_ID),
            type=glom(hit, Coalesce(Attribute.TYPE, default=None)),
            path=glom(hit, (Coalesce(Attribute.PATH, default=[]), Iter().all())),
            name=glom(hit, Coalesce(Attribute.NAME, default=None)),
        )


class ElasticAggConfig:
    arbitrary_types_allowed = True
    allow_population_by_field_name = True
    extra = Extra.forbid


class ElasticAgg(BaseModel, ABC):

    class Config(ElasticAggConfig):
        pass

    @classmethod
    def parse_elastic_response(
        cls: Type[_ELASTIC_AGG], response: Response,
    ) -> _ELASTIC_AGG:
        raise NotImplementedError()


class BucketAgg(ElasticAgg, ABC):
    pass


class CollectionMaterialsCount(PydanticBaseModel):
    noderef_id: UUID
    materials_count: int


class DescendantCollectionsMaterialsCounts(BucketAgg):

    results: List[CollectionMaterialsCount]

    @classmethod
    def parse_elastic_response(
        cls: Type[_DESCENDANT_COLLECTIONS_MATERIALS_COUNTS], response: Response,
    ) -> _DESCENDANT_COLLECTIONS_MATERIALS_COUNTS:
        results = glom(
            response,
            (
                "aggregations.grouped_by_collection.buckets",
                [
                    {
                        "noderef_id": "key.noderef_id",
                        "materials_count": "doc_count",
                    }
                ],
            ),
        )
        return cls.construct(
            results=[CollectionMaterialsCount.construct(**record) for record in results],
        )