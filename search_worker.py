import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

import database
import downloader

if TYPE_CHECKING:
    import sqlite3

    from models import SearchResult


class SearchWorker(QThread):
    """Worker thread to run backend processing and database queries."""

    results_found: Signal = Signal(list)
    error: Signal = Signal(str)
    progress: Signal = Signal(int, int, str)

    def __init__(
        self,
        db_path: str,
        source_type: str,
        target_id: str,
        query_text: str,
        start_date: datetime.date | None,
        end_date: datetime.date | None,
        limit: int = 100,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the search work with db and basic query info."""
        super().__init__(parent)
        self.db_path: str = db_path
        self.source_type: str = source_type
        self.target_id: str = target_id
        self.query_text: str = query_text
        self.start_date: datetime.date | None = start_date
        self.end_date: datetime.date | None = end_date
        self.limit: int = limit

    def run(self) -> None:
        """Execute the target processing and search in the background."""
        conn: sqlite3.Connection | None = None

        try:
            conn = database.get_connection(self.db_path)

            if conn is not None:
                database.init_db(conn)

                downloader.process_target(
                    conn=conn,
                    source_type=self.source_type,
                    target_id=self.target_id,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    progress_callback=self.progress.emit,
                )

                if self.query_text:
                    self.progress.emit(100, 100, "Querying database...")
                    results: list[SearchResult] = database.search_transcripts(
                        conn=conn,
                        query=self.query_text,
                        start_date=self.start_date,
                        end_date=self.end_date,
                        limit=self.limit,
                    )
                    self.results_found.emit(results)

        except Exception as e:
            self.error.emit(f"Error:{e!s}")
        finally:
            if conn is not None:
                conn.close()
