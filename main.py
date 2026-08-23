import sqlite3
import sys

from PySide6.QtWidgets import QApplication

import downloader
from main_window import MainWindow
from models import SearchResult


def get_all_transcripts(
    conn: sqlite3.Connection,
    limit: int = 1000,
) -> list[SearchResult]:
    """Fetch all transcript entries in the database for debugging."""
    sql: str = """
        SELECT
            fts.video_id,
            fts.start_time,
            v.title,
            v.channel,
            fts.text AS snippet_text,
            0.0 AS rank
        FROM transcripts_fts AS fts
        JOIN videos AS v ON v.video_id = fts.video_id
        LIMIT ?;
    """

    cursor: sqlite3.Cursor = conn.execute(sql, (limit,))
    rows: list[sqlite3.Row] = cursor.fetchall()

    return [
        SearchResult(
            video_id=str(row["video_id"]),
            title=str(row["title"] or "Unknown Title"),
            channel=str(row["channel"] or "Unknown Channel"),
            start_time=float(row["start_time"]),
            snippet=str(row["snippet_text"]),
            rank=float(row["rank"]),
        )
        for row in rows
    ]


if __name__ == "__main__":
    url: str = downloader._build_playlist_url(
        "PLrMS357ieiqS894xcyXj2wwG8H05Rutvo",
    )
    # conn = sqlite3.Connection("transcripts.db")
    # print(get_all_transcripts(conn))
    app: QApplication = QApplication(sys.argv)
    window: MainWindow = MainWindow()
    window.show()
    sys.exit(app.exec())
