from datetime import datetime, timedelta
from typing import Any

from shared.integrations.protocols import ElasticsearchClientProtocol


class MockElasticsearchClient(ElasticsearchClientProtocol):
    _MOCK_LOGS: list[dict[str, Any]] = [
        {
            "@timestamp": (datetime.utcnow() - timedelta(minutes=30)).isoformat(),
            "level": "ERROR",
            "service.name": "Dizi",
            "service.environment": "Development",
            "message": "ConnectionTimeout calling payment-service:8080/process",
            "trace.id": "abc123trace",
            "error.type": "System.Net.Http.HttpRequestException",
        },
        {
            "@timestamp": (datetime.utcnow() - timedelta(minutes=25)).isoformat(),
            "level": "ERROR",
            "service.name": "Dizi",
            "service.environment": "Development",
            "message": "504 Gateway Timeout on POST /api/v1/payments",
            "trace.id": "def456trace",
            "http.response.status_code": 504,
        },
        {
            "@timestamp": (datetime.utcnow() - timedelta(minutes=20)).isoformat(),
            "level": "WARN",
            "service.name": "Dizi",
            "service.environment": "Development",
            "message": "Circuit breaker OPEN for external-psp connection",
            "trace.id": "ghi789trace",
        },
    ]

    async def search_logs(
        self,
        query: str,
        index_pattern: str | None = None,
        size: int = 50,
        time_range_minutes: int = 60,
        service_name: str | None = None,
        service_environment: str | None = None,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results = [
            log
            for log in self._MOCK_LOGS
            if any(query_lower in str(v).lower() for v in log.values())
        ]
        if service_name:
            results = [log for log in results if log.get("service.name") == service_name]
        if service_environment:
            results = [
                log for log in results if log.get("service.environment") == service_environment
            ]
        return results[:size]

    async def search_traces(
        self,
        service_name: str | None = None,
        error: bool = True,
        time_range_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        traces = [
            {
                "trace.id": "abc123trace",
                "service.name": "Dizi",
                "transaction.duration.us": 30000000,
                "error": True,
                "span.name": "POST /api/v1/payments",
            },
            {
                "trace.id": "def456trace",
                "service.name": "Dizi",
                "transaction.duration.us": 25000000,
                "error": True,
                "span.name": "external-psp/process",
            },
        ]
        if service_name:
            traces = [t for t in traces if t.get("service.name") == service_name]
        if error:
            traces = [t for t in traces if t.get("error")]
        return traces


class RealElasticsearchClient(ElasticsearchClientProtocol):
    def __init__(self, url: str, username: str, password: str, index_pattern: str):
        from elasticsearch import AsyncElasticsearch

        self._client = AsyncElasticsearch(
            hosts=[url],
            basic_auth=(username, password),
            verify_certs=False,
        )
        self._index_pattern = index_pattern

    async def search_logs(
        self,
        query: str,
        index_pattern: str | None = None,
        size: int = 50,
        time_range_minutes: int = 60,
        service_name: str | None = None,
        service_environment: str | None = None,
    ) -> list[dict[str, Any]]:
        index = index_pattern or self._index_pattern
        filters: list[dict[str, Any]] = [
            {"range": {"@timestamp": {"gte": f"now-{time_range_minutes}m"}}}
        ]
        if service_name:
            filters.append({"term": {"service.name": service_name}})
        if service_environment:
            filters.append({"term": {"service.environment": service_environment}})

        body = {
            "query": {
                "bool": {
                    "must": [{"query_string": {"query": query or "*"}}],
                    "filter": filters,
                }
            },
            "size": size,
            "sort": [{"@timestamp": "desc"}],
        }
        result = await self._client.search(index=index, body=body)
        return [hit["_source"] for hit in result["hits"]["hits"]]

    async def search_traces(
        self,
        service_name: str | None = None,
        error: bool = True,
        time_range_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        must: list[dict[str, Any]] = [
            {"range": {"@timestamp": {"gte": f"now-{time_range_minutes}m"}}}
        ]
        if service_name:
            must.append({"term": {"service.name": service_name}})
        if error:
            must.append({"term": {"error": True}})

        body = {"query": {"bool": {"must": must}}, "size": 50}
        result = await self._client.search(index="apm-*-transaction*", body=body)
        return [hit["_source"] for hit in result["hits"]["hits"]]
