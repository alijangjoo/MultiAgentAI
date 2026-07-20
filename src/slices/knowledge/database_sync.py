"""MySQL schema introspection and ChromaDB synchronization for Knowledge Agent."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import pymysql
from pymysql.cursors import DictCursor

from core.config import Settings, get_settings
from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.models.collections import KnowledgeCollection
from slices.knowledge.rag.vector_store import ChromaKnowledgeStore, get_knowledge_store

DatabaseEnvironment = Literal["dev", "stage"]


class DatabaseSyncError(RuntimeError):
    """Raised when database metadata cannot be synchronized safely."""


@dataclass(frozen=True)
class DatabaseConnectionConfig:
    environment: DatabaseEnvironment
    host: str
    port: int
    user: str
    password: str
    database: str
    connect_timeout: int

    @property
    def configured(self) -> bool:
        return bool(self.host.strip() and self.user.strip() and self.database.strip())

    def public_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "configured": self.configured,
            "host": self.host or "(not configured)",
            "port": self.port,
            "database": self.database,
            "user": self.user or "(not configured)",
            "password_configured": bool(self.password),
        }


def _connection_config(
    environment: DatabaseEnvironment, settings: Settings
) -> DatabaseConnectionConfig:
    if environment == "dev":
        return DatabaseConnectionConfig(
            environment=environment,
            host=settings.dizi_db_dev_host,
            port=settings.dizi_db_dev_port,
            user=settings.dizi_db_dev_user,
            password=settings.dizi_db_dev_password,
            database=settings.dizi_db_dev_name,
            connect_timeout=settings.dizi_db_connect_timeout_seconds,
        )
    if environment == "stage":
        return DatabaseConnectionConfig(
            environment=environment,
            host=settings.dizi_db_stage_host,
            port=settings.dizi_db_stage_port,
            user=settings.dizi_db_stage_user,
            password=settings.dizi_db_stage_password,
            database=settings.dizi_db_stage_name,
            connect_timeout=settings.dizi_db_connect_timeout_seconds,
        )
    raise ValueError(f"Unsupported database environment: {environment}")


def _stable_doc_id(environment: str, database: str, object_name: str) -> str:
    key = f"{environment}:{database}:{object_name}".lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"mysql-schema-{digest}"


class DatabaseKnowledgeSyncService:
    """Synchronize schema metadata only; application row values are never read."""

    def __init__(
        self,
        *,
        store: ChromaKnowledgeStore | None = None,
        run_repo: AgentRunRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_knowledge_store()
        self._run_repo = run_repo or AgentRunRepository()
        self._sync_locks = {
            "dev": asyncio.Lock(),
            "stage": asyncio.Lock(),
        }

    def list_environments(self) -> list[dict[str, Any]]:
        return [
            self._environment_summary(environment)
            for environment in ("dev", "stage")
        ]

    def _environment_summary(
        self, environment: DatabaseEnvironment
    ) -> dict[str, Any]:
        config = _connection_config(environment, self._settings)
        source_prefix = (
            f"mysql-schema:{environment}:{config.database}:"
        ).lower()
        documents = self._store.list_documents(
            collection=KnowledgeCollection.DATABASE_SCHEMA.value,
            limit=1000,
        )
        owned = [
            item
            for item in documents
            if str(item.get("source") or "").lower().startswith(source_prefix)
        ]
        table_documents = [
            item for item in owned if "database-overview" not in (item.get("tags") or [])
        ]
        timestamps = [
            str(item["created_at"])
            for item in owned
            if item.get("created_at")
        ]
        return {
            **config.public_dict(),
            "collection": KnowledgeCollection.DATABASE_SCHEMA.value,
            "documents": len(owned),
            "tables": len(table_documents),
            "last_synced_at": max(timestamps) if timestamps else None,
        }

    async def connection_status(
        self, environment: DatabaseEnvironment, *, test: bool = False
    ) -> dict[str, Any]:
        summary = self._environment_summary(environment)
        if not test:
            return summary
        config = _connection_config(environment, self._settings)
        if not config.configured:
            return {
                **summary,
                "reachable": False,
                "connection_error": "Host, user, and database must be configured in .env",
            }
        try:
            server = await asyncio.to_thread(self._test_connection, config)
            return {**summary, "reachable": True, "server_version": server}
        except Exception as exc:
            return {
                **summary,
                "reachable": False,
                "connection_error": self._safe_error(exc),
            }

    def purge(self, environment: DatabaseEnvironment) -> dict[str, Any]:
        config = _connection_config(environment, self._settings)
        source_prefix = (
            f"mysql-schema:{environment}:{config.database}:"
        ).lower()
        documents_deleted = 0
        chunks_deleted = 0
        for item in self._store.list_documents(
            collection=KnowledgeCollection.DATABASE_SCHEMA.value,
            limit=1000,
        ):
            if str(item.get("source") or "").lower().startswith(source_prefix):
                documents_deleted += 1
                chunks_deleted += self._store.delete_document(item["id"])
        return {
            "environment": environment,
            "database": config.database,
            "documents_deleted": documents_deleted,
            "chunks_deleted": chunks_deleted,
        }

    async def sync(self, environment: DatabaseEnvironment) -> dict[str, Any]:
        lock = self._sync_locks[environment]
        if lock.locked():
            raise DatabaseSyncError(
                f"A {environment} database schema synchronization is already running"
            )
        async with lock:
            return await self._sync_once(environment)

    async def _sync_once(
        self, environment: DatabaseEnvironment
    ) -> dict[str, Any]:
        config = _connection_config(environment, self._settings)
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.KNOWLEDGE_INGEST.value,
            agent_name=AgentName.SAGE,
            input_payload={
                "source": "mysql_schema",
                "environment": environment,
                "database": config.database,
            },
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.SAGE,
            "database_sync_started",
            f"Starting {environment} MySQL schema synchronization",
            {"environment": environment, "database": config.database},
        )

        if not config.configured:
            error = (
                f"{environment} database is not configured. Set DIZI_DB_"
                f"{environment.upper()}_HOST, USER, PASSWORD, and NAME in .env."
            )
            await self._fail_run(run_id, environment, error)
            raise DatabaseSyncError(error)

        try:
            result = await asyncio.to_thread(self._introspect_and_upsert, config)
        except Exception as exc:
            error = self._safe_error(exc)
            await self._fail_run(run_id, environment, error)
            raise DatabaseSyncError(error) from exc

        output = {
            "source": "mysql_schema",
            "environment": environment,
            "database": config.database,
            **result,
        }
        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload=output,
        )
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.SAGE,
            "database_sync_completed",
            (
                f"Stored {result['tables']} schema objects from "
                f"{environment} in ChromaDB"
            ),
            output,
        )
        return {**output, "run_id": run_id}

    async def _fail_run(
        self, run_id: str, environment: str, error: str
    ) -> None:
        await self._run_repo.update_run(
            run_id,
            status=RunStatus.FAILED,
            error_message=error,
        )
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.SAGE,
            "database_sync_failed",
            f"{environment} MySQL schema synchronization failed",
            {"environment": environment, "error": error},
        )

    @staticmethod
    def _connect(config: DatabaseConnectionConfig):
        return pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            connect_timeout=config.connect_timeout,
            read_timeout=max(config.connect_timeout, 20),
            write_timeout=config.connect_timeout,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
        )

    def _test_connection(self, config: DatabaseConnectionConfig) -> str:
        with self._connect(config) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION() AS server_version")
                row = cursor.fetchone() or {}
        return str(row.get("server_version") or "MySQL")

    def _introspect_and_upsert(
        self, config: DatabaseConnectionConfig
    ) -> dict[str, Any]:
        with self._connect(config) as connection:
            schema = self._read_schema(connection, config.database)

        generated_at = datetime.now(timezone.utc).isoformat()
        active_ids: set[str] = set()
        chunks_created = 0

        for table in schema["tables"]:
            doc_id = _stable_doc_id(
                config.environment,
                config.database,
                table["name"],
            )
            active_ids.add(doc_id)
            content = self._render_table_document(
                environment=config.environment,
                database=config.database,
                table=table,
            )
            result = self._store.upsert_document(
                collection=KnowledgeCollection.DATABASE_SCHEMA.value,
                title=(
                    f"[{config.environment}] "
                    f"{config.database}.{table['name']} schema"
                ),
                content=content,
                doc_id=doc_id,
                tags=[
                    "mysql",
                    "database-schema",
                    config.environment,
                    table["type"].lower().replace(" ", "-"),
                ],
                source=(
                    f"mysql-schema:{config.environment}:"
                    f"{config.database}:{table['name']}"
                ),
            )
            chunks_created += int(result["chunks_created"])

        overview_id = _stable_doc_id(
            config.environment,
            config.database,
            "__database_overview__",
        )
        active_ids.add(overview_id)
        overview = self._render_overview(
            environment=config.environment,
            database=config.database,
            tables=schema["tables"],
            generated_at=generated_at,
        )
        overview_result = self._store.upsert_document(
            collection=KnowledgeCollection.DATABASE_SCHEMA.value,
            title=f"[{config.environment}] {config.database} database overview",
            content=overview,
            doc_id=overview_id,
            tags=["mysql", "database-schema", "database-overview", config.environment],
            source=(
                f"mysql-schema:{config.environment}:"
                f"{config.database}:__database_overview__"
            ),
        )
        chunks_created += int(overview_result["chunks_created"])

        stale_documents, stale_chunks = self._delete_stale_documents(
            config, active_ids
        )
        return {
            "documents_ingested": len(active_ids),
            "tables": len(schema["tables"]),
            "columns": sum(len(table["columns"]) for table in schema["tables"]),
            "foreign_keys": sum(
                len(table["foreign_keys"]) for table in schema["tables"]
            ),
            "chunks_created": chunks_created,
            "stale_documents_deleted": stale_documents,
            "stale_chunks_deleted": stale_chunks,
            "generated_at": generated_at,
        }

    def _delete_stale_documents(
        self,
        config: DatabaseConnectionConfig,
        active_ids: set[str],
    ) -> tuple[int, int]:
        source_prefix = (
            f"mysql-schema:{config.environment}:{config.database}:"
        ).lower()
        documents_deleted = 0
        chunks_deleted = 0
        for item in self._store.list_documents(
            collection=KnowledgeCollection.DATABASE_SCHEMA.value,
            limit=1000,
        ):
            source = str(item.get("source") or "").lower()
            if source.startswith(source_prefix) and item["id"] not in active_ids:
                documents_deleted += 1
                chunks_deleted += self._store.delete_document(item["id"])
        return documents_deleted, chunks_deleted

    @staticmethod
    def _read_schema(connection: Any, database: str) -> dict[str, Any]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT TABLE_NAME AS table_name, TABLE_TYPE AS table_type,
                       ENGINE AS engine, TABLE_ROWS AS estimated_rows,
                       TABLE_COMMENT AS table_comment
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME
                """,
                (database,),
            )
            table_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
                       ORDINAL_POSITION AS ordinal_position,
                       COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable,
                       COLUMN_DEFAULT AS column_default, COLUMN_KEY AS column_key,
                       EXTRA AS extra, COLUMN_COMMENT AS column_comment
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """,
                (database,),
            )
            column_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT TABLE_NAME AS table_name, INDEX_NAME AS index_name,
                       NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS seq_in_index,
                       COLUMN_NAME AS column_name, INDEX_TYPE AS index_type
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
                """,
                (database,),
            )
            index_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT TABLE_NAME AS table_name,
                       CONSTRAINT_NAME AS constraint_name,
                       COLUMN_NAME AS column_name,
                       REFERENCED_TABLE_NAME AS referenced_table_name,
                       REFERENCED_COLUMN_NAME AS referenced_column_name
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s
                  AND REFERENCED_TABLE_NAME IS NOT NULL
                ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
                """,
                (database,),
            )
            foreign_key_rows = cursor.fetchall()

        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        for row in column_rows:
            columns_by_table.setdefault(row["table_name"], []).append(row)

        indexes_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        for row in index_rows:
            table_indexes = indexes_by_table.setdefault(row["table_name"], {})
            index = table_indexes.setdefault(
                row["index_name"],
                {
                    "name": row["index_name"],
                    "unique": not bool(row["non_unique"]),
                    "type": row["index_type"],
                    "columns": [],
                },
            )
            index["columns"].append(row["column_name"] or "<functional-expression>")

        fks_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        for row in foreign_key_rows:
            table_fks = fks_by_table.setdefault(row["table_name"], {})
            fk = table_fks.setdefault(
                row["constraint_name"],
                {
                    "name": row["constraint_name"],
                    "columns": [],
                    "referenced_table": row["referenced_table_name"],
                    "referenced_columns": [],
                },
            )
            fk["columns"].append(row["column_name"])
            fk["referenced_columns"].append(row["referenced_column_name"])

        tables = []
        for row in table_rows:
            name = row["table_name"]
            tables.append(
                {
                    "name": name,
                    "type": row["table_type"],
                    "engine": row["engine"],
                    "estimated_rows": row["estimated_rows"],
                    "comment": row["table_comment"] or "",
                    "columns": columns_by_table.get(name, []),
                    "indexes": list(indexes_by_table.get(name, {}).values()),
                    "foreign_keys": list(fks_by_table.get(name, {}).values()),
                }
            )
        return {"tables": tables}

    @staticmethod
    def _render_table_document(
        *,
        environment: str,
        database: str,
        table: dict[str, Any],
    ) -> str:
        lines = [
            f"# MySQL schema: {database}.{table['name']}",
            "",
            f"- Environment: {environment}",
            f"- Object type: {table['type']}",
            f"- Engine: {table['engine'] or 'n/a'}",
            f"- Estimated rows: {table['estimated_rows'] or 0}",
            f"- Comment: {table['comment'] or '(none)'}",
            "- Data policy: schema metadata only; no application row values are stored.",
            "",
            "## Columns",
        ]
        for column in table["columns"]:
            attributes = [
                str(column["column_type"]),
                "NULL" if column["is_nullable"] == "YES" else "NOT NULL",
            ]
            if column["column_key"]:
                attributes.append(str(column["column_key"]))
            if column["column_default"] is not None:
                attributes.append(f"default={column['column_default']!r}")
            if column["extra"]:
                attributes.append(str(column["extra"]))
            if column["column_comment"]:
                attributes.append(f"comment={column['column_comment']}")
            lines.append(
                f"- {column['column_name']}: " + "; ".join(attributes)
            )

        lines.extend(["", "## Indexes"])
        if table["indexes"]:
            for index in table["indexes"]:
                unique = "UNIQUE" if index["unique"] else "NON-UNIQUE"
                lines.append(
                    f"- {index['name']}: {unique} {index['type']} "
                    f"({', '.join(index['columns'])})"
                )
        else:
            lines.append("- (none)")

        lines.extend(["", "## Foreign keys"])
        if table["foreign_keys"]:
            for fk in table["foreign_keys"]:
                lines.append(
                    f"- {fk['name']}: ({', '.join(fk['columns'])}) -> "
                    f"{fk['referenced_table']}"
                    f"({', '.join(fk['referenced_columns'])})"
                )
        else:
            lines.append("- (none)")
        return "\n".join(lines)

    @staticmethod
    def _render_overview(
        *,
        environment: str,
        database: str,
        tables: list[dict[str, Any]],
        generated_at: str,
    ) -> str:
        lines = [
            f"# MySQL database overview: {database}",
            "",
            f"- Environment: {environment}",
            f"- Generated at: {generated_at}",
            f"- Schema objects: {len(tables)}",
            "- Data policy: metadata only; no application row values are stored.",
            "",
            "## Objects",
        ]
        for table in tables:
            lines.append(
                f"- {table['name']} ({table['type']}): "
                f"{len(table['columns'])} columns, "
                f"{len(table['foreign_keys'])} foreign keys"
            )
        return "\n".join(lines)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, pymysql.MySQLError):
            code = exc.args[0] if exc.args else "unknown"
            message = exc.args[1] if len(exc.args) > 1 else "MySQL connection failed"
            return f"MySQL error {code}: {message}"
        return str(exc) or exc.__class__.__name__
