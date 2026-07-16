import time
from typing import Any

from shared.integrations.protocols import MattermostClientProtocol


class MockMattermostClient(MattermostClientProtocol):
    _MOCK_POSTS: list[dict[str, Any]] = [
        {
            "id": "post-001",
            "channel_id": "disaster",
            "user_id": "ops-user",
            "message": (
                "[INCIDENT] Payment gateway timeout errors since 09:15 UTC. "
                "Multiple customers reporting failed checkout. "
                "Error: ConnectionTimeout to payment-service:8080"
            ),
            "create_at": int(time.time() * 1000) - 3600000,
            "props": {"priority": "high"},
        },
        {
            "id": "post-002",
            "channel_id": "disaster",
            "user_id": "commercial-user",
            "message": (
                "Commercial team confirming ~50 failed transactions in last hour. "
                "Revenue impact estimated at $12K."
            ),
            "create_at": int(time.time() * 1000) - 3000000,
            "props": {},
        },
        {
            "id": "post-003",
            "channel_id": "disaster",
            "user_id": "ops-user",
            "message": (
                "Kibana shows spike in 504 errors on /api/v1/payments endpoint. "
                "APM trace shows downstream timeout to external PSP."
            ),
            "create_at": int(time.time() * 1000) - 2400000,
            "props": {},
        },
    ]

    async def get_channel_posts(
        self,
        channel_id: str,
        since: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        posts = self._MOCK_POSTS
        if since:
            posts = [p for p in posts if p["create_at"] >= since]
        return posts[:limit]

    async def post_message(self, channel_id: str, message: str) -> dict[str, Any]:
        return {"id": "post-new", "channel_id": channel_id, "message": message}


class RealMattermostClient(MattermostClientProtocol):
    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._token = token

    async def get_channel_posts(
        self,
        channel_id: str,
        since: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        import httpx

        params: dict[str, Any] = {"per_page": limit}
        if since:
            params["since"] = since

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._url}/api/v4/channels/{channel_id}/posts",
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            posts_map = data.get("posts", {})
            order = data.get("order", [])
            return [posts_map[post_id] for post_id in order if post_id in posts_map]

    async def post_message(self, channel_id: str, message: str) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/api/v4/posts",
                headers={"Authorization": f"Bearer {self._token}"},
                json={"channel_id": channel_id, "message": message},
            )
            response.raise_for_status()
            return response.json()
