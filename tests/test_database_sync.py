import unittest
from contextlib import nullcontext
from typing import Any

from slices.knowledge.database_sync import (
    DatabaseConnectionConfig,
    DatabaseKnowledgeSyncService,
    _stable_doc_id,
)


class FakeStore:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def upsert_document(
        self,
        collection: str,
        title: str,
        content: str,
        *,
        doc_id: str,
        tags: list[str],
        source: str,
    ) -> dict[str, Any]:
        self.documents[doc_id] = {
            "id": doc_id,
            "collection": collection,
            "title": title,
            "content": content,
            "tags": tags,
            "source": source,
        }
        return {"id": doc_id, "chunks_created": 1}

    def list_documents(
        self, collection: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return [
            doc
            for doc in self.documents.values()
            if not collection or doc["collection"] == collection
        ][:limit]

    def delete_document(self, doc_id: str) -> int:
        return 1 if self.documents.pop(doc_id, None) else 0


class FakeDatabaseService(DatabaseKnowledgeSyncService):
    schema: dict[str, Any] = {
        "tables": [
            {
                "name": "orders",
                "type": "BASE TABLE",
                "engine": "InnoDB",
                "estimated_rows": 42,
                "comment": "Order aggregate",
                "columns": [
                    {
                        "column_name": "id",
                        "column_type": "bigint",
                        "is_nullable": "NO",
                        "column_default": None,
                        "column_key": "PRI",
                        "extra": "auto_increment",
                        "column_comment": "",
                    },
                    {
                        "column_name": "customer_id",
                        "column_type": "bigint",
                        "is_nullable": "NO",
                        "column_default": None,
                        "column_key": "MUL",
                        "extra": "",
                        "column_comment": "",
                    },
                ],
                "indexes": [
                    {
                        "name": "PRIMARY",
                        "unique": True,
                        "type": "BTREE",
                        "columns": ["id"],
                    }
                ],
                "foreign_keys": [
                    {
                        "name": "fk_orders_customer",
                        "columns": ["customer_id"],
                        "referenced_table": "customers",
                        "referenced_columns": ["id"],
                    }
                ],
            }
        ]
    }

    @staticmethod
    def _connect(config: DatabaseConnectionConfig):
        del config
        return nullcontext(object())

    @staticmethod
    def _read_schema(connection: Any, database: str) -> dict[str, Any]:
        del connection, database
        return FakeDatabaseService.schema


class DatabaseSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.service = FakeDatabaseService(
            store=self.store,  # type: ignore[arg-type]
            run_repo=object(),  # type: ignore[arg-type]
        )
        self.config = DatabaseConnectionConfig(
            environment="dev",
            host="mysql.internal",
            port=3306,
            user="knowledge_reader",
            password="secret-value",
            database="dizi_db",
            connect_timeout=5,
        )

    def test_public_connection_config_never_exposes_password(self) -> None:
        public = self.config.public_dict()

        self.assertNotIn("password", public)
        self.assertTrue(public["password_configured"])

    def test_schema_sync_stores_table_and_overview_without_row_values(self) -> None:
        result = self.service._introspect_and_upsert(self.config)

        self.assertEqual(result["tables"], 1)
        self.assertEqual(result["columns"], 2)
        self.assertEqual(result["foreign_keys"], 1)
        self.assertEqual(len(self.store.documents), 2)
        joined = "\n".join(doc["content"] for doc in self.store.documents.values())
        self.assertIn("orders", joined)
        self.assertIn("customer_id", joined)
        self.assertIn("schema metadata only", joined)
        self.assertNotIn("secret-value", joined)

    def test_document_ids_are_stable_and_environment_specific(self) -> None:
        dev_id = _stable_doc_id("dev", "dizi_db", "orders")

        self.assertEqual(dev_id, _stable_doc_id("dev", "dizi_db", "orders"))
        self.assertNotEqual(
            dev_id,
            _stable_doc_id("stage", "dizi_db", "orders"),
        )


if __name__ == "__main__":
    unittest.main()
