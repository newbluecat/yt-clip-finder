from typing import Final

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import SearchResult
from search_worker import SearchWorker

MAX_QUERY_LENGTH: Final[int] = 50


class MainWindow(QMainWindow):
    """Main window interface."""

    def __init__(self) -> None:  # noqa: PLR0915
        """Initialize the main UI."""
        super().__init__()
        self.setWindowTitle("YouTube Transcript Search")
        self.resize(650, 700)

        central_widget: QWidget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout: QVBoxLayout = QVBoxLayout(central_widget)

        # search results table
        self.results_table: QTableWidget = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Title", "Channel", "Time (s)", "Snippet"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setShowGrid(False)

        main_layout.addWidget(self.results_table, stretch=1)

        # source selection dropdown
        options_layout: QVBoxLayout = QVBoxLayout()

        source_id_row: QHBoxLayout = QHBoxLayout()
        source_label: QLabel = QLabel("Source:")
        self.source_combo: QComboBox = QComboBox()
        self.source_combo.addItems(
            [
                "Playlist",
                "Channel (Videos)",
                "Channel (Live)",
            ],
        )

        # id input text box
        id_label: QLabel = QLabel("ID:")
        self.id_input: QLineEdit = QLineEdit()
        self.source_combo.currentTextChanged.connect(self.on_source_changed)
        self.on_source_changed(self.source_combo.currentText())

        source_id_row.addWidget(source_label)
        source_id_row.addWidget(self.source_combo)
        source_id_row.addSpacing(30)
        source_id_row.addWidget(id_label)
        source_id_row.addWidget(self.id_input, stretch=1)
        options_layout.addLayout(source_id_row)

        # upload date filter with selection
        date_row: QHBoxLayout = QHBoxLayout()
        date_label: QLabel = QLabel("Upload Date:")

        self.date_any_radio: QRadioButton = QRadioButton("Any")
        self.date_any_radio.setChecked(True)

        self.date_custom_radio: QRadioButton = QRadioButton("Custom Range:")

        self.date_from: QDateEdit = QDateEdit()
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setDate(QDate.currentDate())
        self.date_from.setEnabled(False)

        date_separator_label: QLabel = QLabel("-")
        self.date_to: QDateEdit = QDateEdit()
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setEnabled(False)

        self.date_custom_radio.toggled.connect(self.on_date_mode_toggled)

        date_row.addWidget(date_label)
        date_row.addSpacing(10)
        date_row.addWidget(self.date_any_radio)
        date_row.addSpacing(10)
        date_row.addWidget(self.date_custom_radio)
        date_row.addWidget(self.date_from)
        date_row.addWidget(date_separator_label)
        date_row.addWidget(self.date_to)
        date_row.addStretch()
        options_layout.addLayout(date_row)

        # query
        query_row: QHBoxLayout = QHBoxLayout()
        query_label: QLabel = QLabel("Query:")
        self.query_input: QLineEdit = QLineEdit()
        self.query_input.setPlaceholderText("Search terms...")
        self.query_input.setMaxLength(MAX_QUERY_LENGTH)
        query_row.addWidget(query_label)
        query_row.addWidget(self.query_input)
        options_layout.addLayout(query_row)

        main_layout.addLayout(options_layout)

        # progress bar
        self.progress_bar: QProgressBar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("")
        main_layout.addWidget(self.progress_bar)

        # search and abort buttons
        button_layout: QHBoxLayout = QHBoxLayout()
        button_layout.addStretch()

        self.abort_button: QPushButton = QPushButton("Abort")
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.on_abort_clicked)

        self.search_button: QPushButton = QPushButton("Search")
        self.search_button.clicked.connect(self.on_search_clicked)

        button_layout.addWidget(self.abort_button)
        button_layout.addWidget(self.search_button)
        main_layout.addLayout(button_layout)

    def on_source_changed(self, text: str) -> None:
        """Update the Target ID placeholder based on the selected source."""
        if text == "Playlist":
            self.id_input.setPlaceholderText("Playlist ID")
        else:
            self.id_input.setPlaceholderText("@creator")

    def on_date_mode_toggled(self, checked: bool) -> None:
        """Enable or disable custom date pickers based on radio selection."""
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)

    def on_search_clicked(self) -> None:
        """Trigger search state and start the background worker."""
        source_type: str = self.source_combo.currentText()
        target_id: str = self.id_input.text().strip()
        query_text: str = self.query_input.text().strip()

        # we catch falsy strings here since an empty string is invalid for a search
        if not target_id:
            return

        self.search_button.setEnabled(False)
        self.abort_button.setEnabled(True)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Fetching video metadata...")

        self.worker: SearchWorker = SearchWorker(
            db_path="transcripts.db",
            source_type=source_type,
            target_id=target_id,
            query_text=query_text,
            parent=self,
        )
        self.worker.results_found.connect(self.on_search_finished)
        self.worker.error.connect(self.on_search_error)
        self.worker.progress.connect(self.on_progress_update)
        self.worker.start()

    def on_search_finished(self, results: list[SearchResult]) -> None:
        """Handle worker completion and table population."""
        result_count: int = len(results)

        if result_count == 0:
            self.progress_bar.setFormat("No results found.")
            return

        self.progress_bar.setFormat(f"Found {result_count} results!")
        self.results_table.clearContents()
        self.results_table.setRowCount(result_count)

        for row, res in enumerate(results):
            self.results_table.setItem(row, 0, QTableWidgetItem(res.title))
            self.results_table.setItem(row, 1, QTableWidgetItem(res.channel))
            self.results_table.setItem(row, 2, QTableWidgetItem(f"{res.start_time:.1f}"))

            snippet_label: QLabel = QLabel(res.snippet)
            snippet_label.setTextFormat(Qt.TextFormat.RichText)
            snippet_label.setContentsMargins(4, 2, 4, 2)  # padding

            self.results_table.setCellWidget(row, 3, snippet_label)

        self.results_table.resizeColumnsToContents()

        # restrict column widths to prevent massive titles or channel breaking layouts
        self.results_table.setColumnWidth(0, min(self.results_table.columnWidth(0), 200))
        self.results_table.setColumnWidth(1, min(self.results_table.columnWidth(1), 150))

        self.search_button.setEnabled(True)
        self.abort_button.setEnabled(False)
        self.progress_bar.setValue(100)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

    def on_search_error(self, err_msg: str) -> None:
        """Handle worker errors."""
        self.search_button.setEnabled(True)
        self.abort_button.setEnabled(False)
        self.progress_bar.setFormat(f"Error: {err_msg}")

    def on_progress_update(self, current: int, total: int, msg: str) -> None:
        """Update the progress bar from the worker thread."""
        if total > 0 and self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{msg} %p%")

    def on_abort_clicked(self) -> None:
        """Trigger abort state in UI (mock handler)."""
        self.abort_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.progress_bar.setFormat("Aborted")

    def clear_results(self) -> None:
        """Clear all rows from the results table."""
        self.results_table.setRowCount(0)
