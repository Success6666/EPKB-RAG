import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

import aiomysql
from aiomysql.cursors import DictCursor

from app.core.config import Settings
from app.langchain_modules.retrieval.scoring import keyword_score, tokenize
from app.langchain_modules.retrieval.vector_store import KnowledgeBaseScope, VectorSearchResult

logger = logging.getLogger(__name__)


class MySqlRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._connection_kwargs = mysql_connection_kwargs(settings)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            connection = await self.connection()
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS rag_python_document_chunk (
                          chunk_id VARCHAR(64) NOT NULL,
                          tenant_id VARCHAR(64) NOT NULL,
                          kb_id VARCHAR(64) NOT NULL,
                          doc_id VARCHAR(128) NOT NULL,
                          chunk_index INT NOT NULL DEFAULT 0,
                          text MEDIUMTEXT NOT NULL,
                          metadata JSON NULL,
                          file_name VARCHAR(255) NULL,
                          source_uri VARCHAR(1024) NULL,
                          page INT NULL,
                          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                          PRIMARY KEY (chunk_id),
                          KEY idx_py_chunk_scope_doc (tenant_id, kb_id, doc_id),
                          KEY idx_py_chunk_scope_index (tenant_id, kb_id, chunk_index),
                          FULLTEXT KEY ft_py_chunk_text (text)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                        """
                    )
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS rag_python_ingest_job (
                          job_key VARCHAR(255) NOT NULL,
                          tenant_id VARCHAR(64) NOT NULL,
                          kb_id VARCHAR(64) NOT NULL,
                          doc_id VARCHAR(128) NOT NULL,
                          status VARCHAR(32) NOT NULL,
                          attempts INT NOT NULL DEFAULT 0,
                          chunk_count INT NOT NULL DEFAULT 0,
                          error_message VARCHAR(1024) NULL,
                          payload JSON NULL,
                          started_at DATETIME NULL,
                          finished_at DATETIME NULL,
                          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                          PRIMARY KEY (job_key),
                          KEY idx_py_job_doc (tenant_id, kb_id, doc_id),
                          KEY idx_py_job_status (status, updated_at)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                        """
                    )
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS rag_python_deleted_document (
                          tenant_id VARCHAR(64) NOT NULL,
                          kb_id VARCHAR(64) NOT NULL,
                          doc_id VARCHAR(128) NOT NULL,
                          deleted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          PRIMARY KEY (tenant_id, kb_id, doc_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                        """
                    )
                await connection.commit()
                self._initialized = True
            except Exception:
                await connection.rollback()
                raise
            finally:
                connection.close()

    async def replace_chunks(
        self,
        scope: KnowledgeBaseScope,
        doc_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    DELETE FROM rag_python_document_chunk
                    WHERE tenant_id=%s AND kb_id=%s AND doc_id=%s
                    """,
                    (scope.tenant_id, scope.kb_id, doc_id),
                )
                if chunks:
                    await cursor.executemany(
                        """
                        INSERT INTO rag_python_document_chunk (
                          chunk_id, tenant_id, kb_id, doc_id, chunk_index, text, metadata,
                          file_name, source_uri, page
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          tenant_id=VALUES(tenant_id),
                          kb_id=VALUES(kb_id),
                          doc_id=VALUES(doc_id),
                          chunk_index=VALUES(chunk_index),
                          text=VALUES(text),
                          metadata=VALUES(metadata),
                          file_name=VALUES(file_name),
                          source_uri=VALUES(source_uri),
                          page=VALUES(page)
                        """,
                        [chunk_row(scope, doc_id, chunk) for chunk in chunks],
                    )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def mark_document_deleted(self, scope: KnowledgeBaseScope, doc_id: str) -> None:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO rag_python_deleted_document (tenant_id, kb_id, doc_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE deleted_at=CURRENT_TIMESTAMP
                    """,
                    (scope.tenant_id, scope.kb_id, doc_id),
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def is_document_deleted(self, scope: KnowledgeBaseScope, doc_id: str) -> bool:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT 1
                    FROM rag_python_deleted_document
                    WHERE tenant_id=%s AND kb_id=%s AND doc_id=%s
                    LIMIT 1
                    """,
                    (scope.tenant_id, scope.kb_id, doc_id),
                )
                return await cursor.fetchone() is not None
        finally:
            connection.close()

    async def delete_chunks(self, scope: KnowledgeBaseScope, doc_id: str) -> int:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    DELETE FROM rag_python_document_chunk
                    WHERE tenant_id=%s AND kb_id=%s AND doc_id=%s
                    """,
                    (scope.tenant_id, scope.kb_id, doc_id),
                )
                deleted = int(cursor.rowcount or 0)
            await connection.commit()
            return deleted
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def keyword_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        metadata_filter: dict[str, Any] | None,
        top_k: int,
    ) -> list[VectorSearchResult]:
        await self.ensure_schema()
        terms = tokenize(query)
        if not terms:
            return []

        keyword_row_groups: list[list[dict[str, Any]]] = []
        if self.settings.mysql_keyword_fulltext_enabled:
            try:
                keyword_row_groups.append(await self._fulltext_search(scope, query, metadata_filter, top_k))
            except aiomysql.MySQLError as exc:
                logger.warning("MySQL FULLTEXT keyword search failed, continuing with LIKE candidates: %s", exc)

        if self.settings.mysql_keyword_like_fallback_enabled:
            keyword_row_groups.append(await self._like_search(scope, terms, metadata_filter, max(top_k * 5, top_k)))

        rows = merge_keyword_rows(keyword_row_groups)
        results: list[VectorSearchResult] = []
        for row in rows:
            metadata = decode_json(row.get("metadata"))
            metadata.setdefault("tenant_id", row.get("tenant_id"))
            metadata.setdefault("kb_id", row.get("kb_id"))
            metadata.setdefault("doc_id", row.get("doc_id"))
            metadata.setdefault("chunk_id", row.get("chunk_id"))
            metadata.setdefault("chunk_index", row.get("chunk_index"))
            metadata.setdefault("file_name", row.get("file_name"))
            metadata.setdefault("source_uri", row.get("source_uri"))
            metadata.setdefault("page", row.get("page"))
            mysql_score = float(row.get("keyword_score") or 0.0)
            local_score = keyword_score(terms, row.get("text") or "")
            score = mysql_score + local_score if mysql_score > 0 else local_score
            if score > 0:
                results.append(
                    VectorSearchResult(
                        chunk_id=str(row["chunk_id"]),
                        text=row.get("text") or "",
                        metadata=metadata,
                        score=score,
                    )
                )
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    async def child_chunks_for_parents(
        self,
        scope: KnowledgeBaseScope,
        parent_ids: list[str],
        metadata_filter: dict[str, Any] | None = None,
        limit_per_parent: int = 8,
    ) -> dict[str, list[VectorSearchResult]]:
        await self.ensure_schema()
        scoped_parent_ids = [parent_id for parent_id in dict.fromkeys(parent_ids) if parent_id]
        if not scoped_parent_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(scoped_parent_ids))
        sql = f"""
            SELECT chunk_id, tenant_id, kb_id, doc_id, chunk_index, text, metadata, file_name, source_uri, page
            FROM rag_python_document_chunk
            WHERE tenant_id=%s
              AND kb_id=%s
              AND JSON_UNQUOTE(JSON_EXTRACT(metadata, '$."chunk_type"')) = 'child'
              AND JSON_UNQUOTE(JSON_EXTRACT(metadata, '$."parent_id"')) IN ({placeholders})
        """
        params: list[Any] = [scope.tenant_id, scope.kb_id, *scoped_parent_ids]
        filter_sql, filter_params = metadata_filter_clause(metadata_filter)
        sql += filter_sql
        sql += " ORDER BY chunk_index ASC"
        params.extend(filter_params)

        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, params)
                rows = list(await cursor.fetchall())
        finally:
            connection.close()

        grouped: dict[str, list[VectorSearchResult]] = {parent_id: [] for parent_id in scoped_parent_ids}
        for row in rows:
            metadata = decode_json(row.get("metadata"))
            metadata.setdefault("tenant_id", row.get("tenant_id"))
            metadata.setdefault("kb_id", row.get("kb_id"))
            metadata.setdefault("doc_id", row.get("doc_id"))
            metadata.setdefault("chunk_id", row.get("chunk_id"))
            metadata.setdefault("chunk_index", row.get("chunk_index"))
            metadata.setdefault("file_name", row.get("file_name"))
            metadata.setdefault("source_uri", row.get("source_uri"))
            metadata.setdefault("page", row.get("page"))
            parent_id = str(metadata.get("parent_id") or "")
            if parent_id not in grouped:
                continue
            if len(grouped[parent_id]) >= limit_per_parent:
                continue
            grouped[parent_id].append(
                VectorSearchResult(
                    chunk_id=str(row["chunk_id"]),
                    text=row.get("text") or "",
                    metadata=metadata,
                    score=0.0,
                )
            )
        return grouped

    async def parent_chunks_by_ids(
        self,
        scope: KnowledgeBaseScope,
        parent_ids: list[str],
        metadata_filter: dict[str, Any] | None = None,
    ) -> dict[str, VectorSearchResult]:
        await self.ensure_schema()
        scoped_parent_ids = [parent_id for parent_id in dict.fromkeys(parent_ids) if parent_id]
        if not scoped_parent_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(scoped_parent_ids))
        sql = f"""
            SELECT chunk_id, tenant_id, kb_id, doc_id, chunk_index, text, metadata, file_name, source_uri, page
            FROM rag_python_document_chunk
            WHERE tenant_id=%s
              AND kb_id=%s
              AND JSON_UNQUOTE(JSON_EXTRACT(metadata, '$."chunk_type"')) = 'parent'
              AND chunk_id IN ({placeholders})
        """
        params: list[Any] = [scope.tenant_id, scope.kb_id, *scoped_parent_ids]
        filter_sql, filter_params = metadata_filter_clause(metadata_filter)
        sql += filter_sql
        params.extend(filter_params)

        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, params)
                rows = list(await cursor.fetchall())
        finally:
            connection.close()

        parents: dict[str, VectorSearchResult] = {}
        for row in rows:
            metadata = decode_json(row.get("metadata"))
            metadata.setdefault("tenant_id", row.get("tenant_id"))
            metadata.setdefault("kb_id", row.get("kb_id"))
            metadata.setdefault("doc_id", row.get("doc_id"))
            metadata.setdefault("chunk_id", row.get("chunk_id"))
            metadata.setdefault("chunk_index", row.get("chunk_index"))
            metadata.setdefault("file_name", row.get("file_name"))
            metadata.setdefault("source_uri", row.get("source_uri"))
            metadata.setdefault("page", row.get("page"))
            parents[str(row["chunk_id"])] = VectorSearchResult(
                chunk_id=str(row["chunk_id"]),
                text=row.get("text") or "",
                metadata=metadata,
                score=0.0,
            )
        return parents

    async def begin_job(
        self,
        job_key: str,
        tenant_id: str,
        kb_id: str,
        doc_id: str,
        payload: dict[str, Any],
        stale_after_seconds: int,
    ) -> str:
        await self.ensure_schema()
        doc_id = fit_identifier(doc_id, 128)
        now = datetime.utcnow()
        stale_before = now - timedelta(seconds=stale_after_seconds)
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT * FROM rag_python_ingest_job WHERE job_key=%s FOR UPDATE", (job_key,))
                row = await cursor.fetchone()
                if row is None:
                    await cursor.execute(
                        """
                        SELECT *
                        FROM rag_python_ingest_job
                        WHERE tenant_id=%s AND kb_id=%s AND doc_id=%s
                        ORDER BY updated_at DESC
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (tenant_id, kb_id, doc_id),
                    )
                    row = await cursor.fetchone()
                if row is None:
                    await cursor.execute(
                        """
                        INSERT INTO rag_python_ingest_job (
                          job_key, tenant_id, kb_id, doc_id, status, attempts, payload, started_at
                        )
                        VALUES (%s, %s, %s, %s, 'processing', 1, %s, %s)
                        """,
                        (job_key, tenant_id, kb_id, doc_id, encode_json(payload), now),
                    )
                    await connection.commit()
                    return "process"

                decision = existing_job_decision(row, stale_before)
                if decision != "process":
                    await connection.commit()
                    return decision

                await cursor.execute(
                    """
                    UPDATE rag_python_ingest_job
                    SET job_key=%s,
                        status='processing',
                        attempts=attempts + 1,
                        error_message=NULL,
                        payload=%s,
                        started_at=%s
                    WHERE job_key=%s
                    """,
                    (job_key, encode_json(payload), now, row["job_key"]),
                )
            await connection.commit()
            return "process"
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def get_job(self, job_key: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT * FROM rag_python_ingest_job WHERE job_key=%s", (job_key,))
                return await cursor.fetchone()
        finally:
            connection.close()

    async def complete_job(self, job_key: str, chunk_count: int) -> None:
        await self._finish_job(job_key, "succeeded", chunk_count, None)

    async def fail_job(self, job_key: str, error_message: str) -> None:
        await self._finish_job(job_key, "failed", 0, error_message)

    async def mark_job_retryable_error(self, job_key: str, error_message: str) -> int:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE rag_python_ingest_job
                    SET status='retry_waiting', error_message=%s
                    WHERE job_key=%s
                    """,
                    (truncate(error_message, 1024), job_key),
                )
                await cursor.execute("SELECT attempts FROM rag_python_ingest_job WHERE job_key=%s", (job_key,))
                row = await cursor.fetchone()
            await connection.commit()
            return int(row["attempts"]) if row else 0
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def connection(self) -> aiomysql.Connection:
        return await aiomysql.connect(**self._connection_kwargs)

    async def _fulltext_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        metadata_filter: dict[str, Any] | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        match_query = build_boolean_fulltext_query(query)
        if not match_query:
            return []
        sql = """
            SELECT chunk_id, tenant_id, kb_id, doc_id, chunk_index, text, metadata, file_name, source_uri, page,
                   MATCH(text) AGAINST (%s IN BOOLEAN MODE) AS keyword_score
            FROM rag_python_document_chunk
            WHERE tenant_id=%s
              AND kb_id=%s
              AND MATCH(text) AGAINST (%s IN BOOLEAN MODE)
        """
        params: list[Any] = [match_query, scope.tenant_id, scope.kb_id, match_query]
        filter_sql, filter_params = metadata_filter_clause(metadata_filter)
        sql += filter_sql
        sql += " ORDER BY keyword_score DESC, updated_at DESC LIMIT %s"
        params.extend(filter_params)
        params.append(top_k)
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, params)
                return list(await cursor.fetchall())
        finally:
            connection.close()

    async def _like_search(
        self,
        scope: KnowledgeBaseScope,
        terms: list[str],
        metadata_filter: dict[str, Any] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        like_terms = terms[:8]
        if not like_terms:
            return []
        where = " OR ".join(["text LIKE %s" for _ in like_terms])
        score = " + ".join(["CASE WHEN text LIKE %s THEN 1 ELSE 0 END" for _ in like_terms])
        sql = f"""
            SELECT chunk_id, tenant_id, kb_id, doc_id, chunk_index, text, metadata, file_name, source_uri, page,
                   ({score}) AS keyword_score
            FROM rag_python_document_chunk
            WHERE tenant_id=%s
              AND kb_id=%s
              AND ({where})
        """
        params: list[Any] = [f"%{escape_like(term)}%" for term in like_terms]
        params.extend([scope.tenant_id, scope.kb_id])
        params.extend([f"%{escape_like(term)}%" for term in like_terms])
        filter_sql, filter_params = metadata_filter_clause(metadata_filter)
        sql += filter_sql
        sql += " ORDER BY keyword_score DESC, updated_at DESC LIMIT %s"
        params.extend(filter_params)
        params.append(limit)
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, params)
                return list(await cursor.fetchall())
        finally:
            connection.close()

    async def _finish_job(self, job_key: str, status: str, chunk_count: int, error_message: str | None) -> None:
        await self.ensure_schema()
        connection = await self.connection()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE rag_python_ingest_job
                    SET status=%s,
                        chunk_count=%s,
                        error_message=%s,
                        finished_at=%s
                    WHERE job_key=%s
                    """,
                    (status, chunk_count, truncate(error_message, 1024) if error_message else None, datetime.utcnow(), job_key),
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()


def mysql_connection_kwargs(settings: Settings) -> dict[str, Any]:
    parsed = urlparse(settings.mysql_dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+aiomysql"}:
        raise ValueError("MYSQL_DSN must use mysql://, mysql+pymysql://, or mysql+aiomysql://")
    query = dict(parse_qsl(parsed.query))
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "db": parsed.path.lstrip("/"),
        "charset": query.get("charset", "utf8mb4"),
        "autocommit": False,
        "cursorclass": DictCursor,
        "connect_timeout": settings.mysql_connect_timeout_seconds,
    }


def chunk_row(scope: KnowledgeBaseScope, doc_id: str, chunk: dict[str, Any]) -> tuple[Any, ...]:
    metadata = dict(chunk.get("metadata") or {})
    metadata.setdefault("tenant_id", scope.tenant_id)
    metadata.setdefault("kb_id", scope.kb_id)
    metadata.setdefault("doc_id", doc_id)
    metadata.setdefault("chunk_id", chunk["id"])
    return (
        chunk["id"],
        scope.tenant_id,
        scope.kb_id,
        doc_id,
        int(metadata.get("chunk_index") or 0),
        chunk.get("text") or "",
        encode_json(metadata),
        metadata.get("file_name"),
        metadata.get("source_uri"),
        metadata.get("page"),
    )


def metadata_filter_clause(metadata_filter: dict[str, Any] | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for key, value in (metadata_filter or {}).items():
        if value is None or not isinstance(value, (str, int, float, bool)):
            continue
        clauses.append("JSON_UNQUOTE(JSON_EXTRACT(metadata, %s)) = %s")
        params.append(f"$.{json_path_key(str(key))}")
        params.append(str(value).lower() if isinstance(value, bool) else str(value))
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def merge_keyword_rows(row_groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rows in row_groups:
        for row in rows:
            chunk_id = str(row.get("chunk_id") or "")
            if not chunk_id:
                continue
            keyword_score_value = float(row.get("keyword_score") or 0.0)
            current = merged.get(chunk_id)
            if current is None:
                current = dict(row)
                current["keyword_score"] = keyword_score_value
                merged[chunk_id] = current
                continue
            current["keyword_score"] = float(current.get("keyword_score") or 0.0) + keyword_score_value
    return sorted(merged.values(), key=lambda row: float(row.get("keyword_score") or 0.0), reverse=True)


def build_boolean_fulltext_query(query: str) -> str:
    terms = [term for term in tokenize(query) if term]
    return " ".join(f"+{term}*" for term in terms[:16])


def json_path_key(key: str) -> str:
    return '"' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def decode_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def truncate(value: str, max_length: int) -> str:
    return value[:max_length]


def fit_identifier(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def existing_job_decision(row: dict[str, Any], stale_before: datetime) -> str:
    status = str(row["status"])
    if status == "succeeded":
        return "succeeded"
    if status == "failed":
        return "failed"
    if status == "retry_waiting":
        return "process"
    updated_at = row.get("updated_at")
    if updated_at is not None and updated_at > stale_before:
        return "processing"
    return "process"
