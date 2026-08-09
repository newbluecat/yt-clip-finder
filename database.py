import sqlite3
from typing import TYPE_CHECKING, Final, NamedTuple

if TYPE_CHECKING:
    from models import TranscriptChunk, VideoMetadata

DB_PATH: Final[str] = "transcripts.db"


class SearchResult(NamedTuple):
    """Results of a search of the sqlite3 database."""

    video_id: str
    title: str
    channel: str
    snippet: str
    rank: float


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create a database connection with foreign keys enabled."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the regular metadata table and FTS5 virtual table."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                channel TEXT,
                channel_id TEXT,
                upload_date TEXT,
                duration_seconds INTEGER,
                status TEXT NOT NULL DEFAULT 'SUCCESS'
            );
            """,
        )

        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
                video_id UNINDEXED,
                start_time UNINDEXED,
                text,
                tokenize='porter unicode61'
            );
            """,
        )


def batch_insert_videos(
    conn: sqlite3.Connection,
    metadata_batch: list[VideoMetadata],
    status_map: dict[str, str],
    chunks: list[TranscriptChunk],
) -> None:
    """Insert or replace video metadata and transcript chunks in one transaction."""
    video_rows: list[tuple[str, str | None, str | None, str | None, str | None, int | None, str]] = []

    for meta in metadata_batch:
        date_str: str | None = meta.upload_date.isoformat() if meta.upload_date is not None else None
        status: str = status_map.get(meta.video_id, "RETRYABLE")
        video_rows.append(
            (
                meta.video_id,
                meta.title,
                meta.channel,
                meta.channel_id,
                date_str,
                meta.duration_seconds,
                status,
            ),
        )

    chunk_rows: list[tuple[str, float, str]] = [(c.video_id, c.start_time, c.text) for c in chunks]

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO videos (
                video_id,
                title,
                channel,
                channel_id,
                upload_date,
                duration_seconds,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            video_rows,
        )

        if chunk_rows:
            # remove any older chunks for these videos before inserting new ones
            video_ids: list[tuple[str]] = [(meta.video_id,) for meta in metadata_batch]
            conn.executemany(
                "DELETE FROM transcripts_fts WHERE video_id = ?;",
                video_ids,
            )

            conn.executemany(
                """
                INSERT INTO transcripts_fts (
                    video_id,
                    start_time,
                    text
                )
                VALUES (?, ?, ?);
                """,
                chunk_rows,
            )


def search_transcripts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 100,
) -> list[SearchResult]:
    """Search using FTS5 MATCH, returning BM25 rank and highlighted snippets."""
    clean_query: str = query.strip()
    if not clean_query:
        return []

    sql: str = """
        SELECT
            fts.video_id,
            v.title,
            v.channel,
            snippet(transcripts_fts, 2, '<b>', '</b>', '...', 15) AS snippet_text,
            bm25(transcripts_fts) AS rank
        FROM transcripts_fts AS fts
        JOIN videos AS v ON v.video_id = fts.video_id
        WHERE transcripts_fts MATCH ?
        ORDER BY rank
        LIMIT ?;
    """

    cursor: sqlite3.Cursor = conn.execute(sql, (clean_query, limit))
    rows: list[sqlite3.Row] = cursor.fetchall()

    results: list[SearchResult] = [
        SearchResult(
            video_id=str(row["video_id"]),
            title=str(row["title"] or "Unknown Title"),
            channel=str(row["channel"] or "Unknown Channel"),
            snippet=str(row["snippet_text"]),
            rank=float(row["rank"]),
        )
        for row in rows
    ]

    return results
