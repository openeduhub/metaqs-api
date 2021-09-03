from elasticsearch_dsl import Search as ElasticSearch
from starlette_context import context

from app.core.config import ELASTIC_INDEX
from .fields import Field
from .utils import handle_text_field


class Search(ElasticSearch):
    def __init__(self, index=ELASTIC_INDEX, **kwargs):
        super(Search, self).__init__(index=index, **kwargs)

    def source(self, source_fields=None, **kwargs):
        if source_fields:
            source_fields = [
                (field.path if isinstance(field, Field) else field)
                for field in source_fields
            ]
        return super(Search, self).source(source_fields, **kwargs)

    def sort(self, *keys):
        return super(Search, self).sort(*[handle_text_field(key) for key in keys])

    def execute(self, ignore_cache=False):
        response = super(Search, self).execute(ignore_cache=ignore_cache)

        context["elastic_queries"] = context.get("elastic_queries", []) + [
            {"query": self.to_dict(), "response": response.to_dict()}
        ]

        return response
