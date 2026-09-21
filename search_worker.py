import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

import database
import downloader

if TYPE_CHECKING:
    import sqlite3

    from models import SearchParams, SearchResult


class SearchWorker(QThread):
    """Worker thread to run backend processing and database queries."""

    results_found: Signal = Signal(list)
    error: Signal = Signal(str)
    progress: Signal = Signal(int, int, str)

    def __init__(
        self,
        db_path: str,
        search: SearchParams,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the search work with db and basic query info."""
        super().__init__(parent)
        self.db_path: str = db_path
        self.search: SearchParams = search
        self._is_cancelled: bool = False

    def cancel(self) -> None:
        """Set is_cancelled to True for cancelling the worker."""
        self._is_cancelled = True

    def run(self) -> None:
        """Execute the target processing and search in the background."""
        conn: sqlite3.Connection | None = None

        try:
            conn = database.get_connection(self.db_path)

            if conn is not None:
                database.init_db(conn)

                downloader.process_target(
                    conn=conn,
                    search_params=self.search,
                    progress_callback=self.progress.emit,
                    is_cancelled=lambda: self._is_cancelled,
                )

                if self._is_cancelled:
                    return

                if self.search.query:
                    self.progress.emit(100, 100, "Querying database...")
                    results: list[SearchResult] = database.search_transcripts(
                        conn=conn,
                        query=self.search.query,
                        start_date=self.search.start_date,
                        end_date=self.search.end_date,
                        limit=self.search.limit,
                    )
                    self.results_found.emit(results)

        except Exception as e:
            raw_msg: str = str(e)

            if "400" in raw_msg:
                parsed_msg: str = (
                    f"Invalid {self.search.source_type} ID: Please make sure that the ID is spelled correctly."
                )
            elif "404" in raw_msg:
                parsed_msg = f"{self.search.source_type} not found. It may be private or deleted."
            elif "not exist" in raw_msg or "unavailable" in raw_msg:
                parsed_msg = f"{self.search.source_type} is unavailable or does not exist."
            else:
                # fallback: strip ANSI codes and print the raw string
                ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
                parsed_msg = ansi_escape.sub("", raw_msg)
                if parsed_msg.startswith("ERROR:"):
                    parsed_msg = parsed_msg.replace("ERROR:", "", 1).strip()

            self.error.emit(parsed_msg)
        finally:
            if conn is not None:
                conn.close()
