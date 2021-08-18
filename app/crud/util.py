import logging
from enum import Enum
from typing import Tuple

from pydantic import BaseModel
from sqlalchemy.sql import ClauseElement
from sqlalchemy.dialects.postgresql import pypostgresql

dialect = pypostgresql.dialect(paramstyle="pyformat")
dialect.implicit_returning = True
dialect.supports_native_enum = True
dialect.supports_smallserial = True
dialect._backslash_escapes = False
dialect.supports_sane_multi_rowcount = True
dialect._has_native_hstore = True


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

    logging.debug("Query: %s\nParams: %s", compiled_query, params)
    return compiled_query, params, compiled._result_columns


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