import hashlib
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .db import connect


class SourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    origin: str = Field(default="", max_length=1000)
    version: str = Field(default="", max_length=100)
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("title", "origin", "version")
    @classmethod
    def trim_metadata(cls, value: str) -> str:
        return value.strip()

    @field_validator("title", "content")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空或全为空白")
        return value


def split_text(content: str) -> list[dict]:
    chunks = []
    for start in range(0, len(content), 700):
        end = min(start + 800, len(content))
        text = content[start:end]
        if text.strip():
            chunks.append({
                "ordinal": len(chunks) + 1,
                "start_offset": start,
                "end_offset": end,
                "text": text,
            })
        if end == len(content):
            break
    return chunks


METADATA_SQL = """
    SELECT s.id, s.title, s.origin, s.version, s.sha256, s.char_count, s.created_at,
           (SELECT COUNT(*) FROM chunks WHERE source_id = s.id) AS chunk_count
    FROM sources s
"""


def list_sources(path: Path) -> list[dict]:
    with connect(path) as connection:
        return [dict(row) for row in connection.execute(METADATA_SQL + " ORDER BY s.id DESC")]


def _read_source(connection, source_id: int) -> dict | None:
    row = connection.execute(METADATA_SQL + " WHERE s.id = ?", (source_id,)).fetchone()
    if row is None:
        return None
    source = dict(row)
    source["content"] = connection.execute("SELECT content FROM sources WHERE id = ?", (source_id,)).fetchone()[0]
    source["chunks"] = [dict(chunk) for chunk in connection.execute(
        "SELECT * FROM chunks WHERE source_id = ? ORDER BY ordinal", (source_id,)
    )]
    return source


def get_source(path: Path, source_id: int) -> dict | None:
    with connect(path) as connection:
        return _read_source(connection, source_id)


def create_source(path: Path, source: SourceCreate) -> dict:
    chunks = split_text(source.content)
    with connect(path) as connection:
        cursor = connection.execute(
            """INSERT INTO sources (title, origin, version, content, sha256, char_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source.title, source.origin, source.version, source.content,
                hashlib.sha256(source.content.encode("utf-8")).hexdigest(),
                len(source.content), datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        source_id = cursor.lastrowid
        connection.executemany(
            """INSERT INTO chunks (source_id, ordinal, start_offset, end_offset, text)
               VALUES (?, ?, ?, ?, ?)""",
            [(source_id, c["ordinal"], c["start_offset"], c["end_offset"], c["text"]) for c in chunks],
        )
        return _read_source(connection, source_id)
