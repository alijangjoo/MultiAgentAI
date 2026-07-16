from typing import Any

from shared.integrations.protocols import ConfluenceClientProtocol


class MockConfluenceClient(ConfluenceClientProtocol):
    _pages: dict[str, dict[str, Any]] = {
        "12345": {
            "id": "12345",
            "title": "Contract API Documentation",
            "space": "ENG",
            "version": 1,
        }
    }

    async def update_page(self, page_id: str, title: str, content: str) -> dict[str, Any]:
        page = self._pages.get(page_id, {"id": page_id, "version": 0})
        page["title"] = title
        page["content"] = content
        page["version"] = page.get("version", 0) + 1
        self._pages[page_id] = page
        return page

    async def create_page(
        self,
        space_key: str,
        title: str,
        content: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        page_id = str(len(self._pages) + 10000)
        page = {
            "id": page_id,
            "title": title,
            "space": space_key,
            "content": content,
            "version": 1,
            "parent_id": parent_id,
        }
        self._pages[page_id] = page
        return page

    async def search_pages(self, query: str, space_key: str | None = None) -> list[dict[str, Any]]:
        results = []
        for page in self._pages.values():
            if query.lower() in page.get("title", "").lower():
                if space_key is None or page.get("space") == space_key:
                    results.append(page)
        return results

    async def get_page_content(self, page_id: str) -> dict[str, Any]:
        page = self._pages.get(
            page_id,
            {
                "id": page_id,
                "title": f"Mock Page {page_id}",
                "content": f"# Mock content for page {page_id}",
            },
        )
        return {
            "id": page.get("id", page_id),
            "title": page.get("title", ""),
            "content": page.get("content", ""),
            "space": page.get("space"),
        }


class RealConfluenceClient(ConfluenceClientProtocol):
    def __init__(self, url: str, username: str, api_token: str):
        from atlassian import Confluence

        self._client = Confluence(url=url, username=username, password=api_token, cloud=False)

    async def update_page(self, page_id: str, title: str, content: str) -> dict[str, Any]:
        current = self._client.get_page_by_id(page_id, expand="body.storage,version")
        version = current["version"]["number"] + 1
        return self._client.update_page(
            page_id=page_id,
            title=title,
            body=content,
            type="page",
            representation="storage",
            minor_edit=False,
            version_comment=f"Updated by Scribe agent to v{version}",
        )

    async def create_page(
        self,
        space_key: str,
        title: str,
        content: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        return self._client.create_page(
            space=space_key,
            title=title,
            body=content,
            parent_id=parent_id,
            type="page",
            representation="storage",
        )

    async def search_pages(self, query: str, space_key: str | None = None) -> list[dict[str, Any]]:
        cql = f'text ~ "{query}"'
        if space_key:
            cql += f' AND space = "{space_key}"'
        results = self._client.cql(cql, limit=10)
        return results.get("results", [])

    async def get_page_content(self, page_id: str) -> dict[str, Any]:
        page = self._client.get_page_by_id(page_id, expand="body.storage,space")
        body = page.get("body", {}).get("storage", {}).get("value", "")
        return {
            "id": page.get("id", page_id),
            "title": page.get("title", ""),
            "content": body,
            "space": page.get("space", {}).get("key"),
        }
