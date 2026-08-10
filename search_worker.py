from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

import database
import downloader
from models import SearchResult

if TYPE_CHECKING:
    import sqlite3


class SearchWorker(QThread):
    """Worker thread to run backend processing and database queries."""

    # Emit the list of SearchResult objects back to the main thread
    results_found: Signal = Signal(list)
    error: Signal = Signal(str)
    progress: Signal = Signal(int, int, str)

    def __init__(self, db_path: str, source_type: str, target_id: str, query_text: str) -> None:
        """Initialize the search work with db and basic query info."""
        super().__init__()
        self.db_path: str = db_path
        self.source_type: str = source_type
        self.target_id: str = target_id
        self.query_text: str = query_text

    def run(self) -> None:
        """Execute the target processing and search in the background."""

        def _progress_cb(current: int, total: int, msg: str) -> None:
            self.progress.emit(current, total, msg)

        conn: sqlite3.Connection | None = None
        results: list[SearchResult] = []

        try:
            conn = database.get_connection(self.db_path)

            if conn is not None:
                # 1. Download and insert new transcripts
                downloader.process_target(
                    conn=conn,
                    source_type=self.source_type,
                    target_id=self.target_id,
                    progress_callback=_progress_cb,
                )

                if self.query_text:
                    self.progress.emit(100, 100, "Querying database...")
                    results = database.search_transcripts(conn=conn, query=self.query_text)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            if conn is not None:
                conn.close()
            # 3. Emit the results list
            self.results_found.emit(results)
