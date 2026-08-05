import sqlite3
from typing import Final, NamedTuple

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
                title,
                content,
                tokenize='porter unicode61'
            );
            """,
        )


def insert_video_record(
    conn: sqlite3.Connection,
    video_id: str,
    title: str | None,
    channel: str | None,
    channel_id: str | None,
    upload_date: str | None,
    duration_seconds: int | None,
    transcript_text: str | None,
    status: str = "SUCCESS",
) -> None:
    """Insert or replace a video record and its FTS5 search index entry."""
    with conn:
        conn.execute(
            """
            INSERT INTO videos (
                video_id,
                title,
                channel,
                channel_id,
                upload_date,
                duration_seconds,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title = excluded.title,
                channel = excluded.channel,
                channel_id = excluded.channel_id,
                upload_date = excluded.upload_date,
                duration_seconds = excluded.duration_seconds,
                status = excluded.status;
            """,
            (
                video_id,
                title,
                channel,
                channel_id,
                upload_date,
                duration_seconds,
                status,
            ),
        )

        if transcript_text is not None:
            # old transcript
            conn.execute(
                "DELETE FROM transcripts_fts WHERE video_id = ?;",
                (video_id,),
            )
            conn.execute(
                """
                INSERT INTO transcripts_fts (video_id, title, content)
                VALUES (?, ?, ?);
                """,
                (video_id, title or "", transcript_text),
            )


def search_transcripts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
    """Search transcripts using FTS5 MATCH, returning BM25 rank and highlighted snippets."""
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

    results: list[SearchResult] = []
    for row in rows:
        results.append(
            SearchResult(
                video_id=str(row["video_id"]),
                title=str(row["title"] or "Unknown Title"),
                channel=str(row["channel"] or "Unknown Channel"),
                snippet=str(row["snippet_text"]),
                rank=float(row["rank"]),
            ),
        )

    return results
