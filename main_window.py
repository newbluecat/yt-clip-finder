import sys
from typing import Any, Final

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

MAX_QUERY_LENGTH: Final[int] = 50


class MainWindow(QMainWindow):
    """Main window interface matching the layout sketch."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Transcript Search")
        self.resize(650, 700)

        central_widget: QWidget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout: QVBoxLayout = QVBoxLayout(central_widget)

        # search results
        self.scroll_area: QScrollArea = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.StyledPanel)

        self.results_container: QWidget = QWidget()
        self.results_layout: QVBoxLayout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.results_container)

        main_layout.addWidget(self.scroll_area, stretch=1)

        # source selection and id input
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

        # upload date filter
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
        self.progress_bar.setValue(100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")
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
        """Trigger search state in UI (mock handler)."""
        self.search_button.setEnabled(False)
        self.abort_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Fetching metadata... %p%")

        # Clear existing cards
        self.clear_results()

    def on_abort_clicked(self) -> None:
        """Trigger abort state in UI (mock handler)."""
        self.abort_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.progress_bar.setFormat("Aborted")

    def clear_results(self) -> None:
        """Remove all child widgets from the results container."""
        while self.results_layout.count() > 0:
            item: Any = self.results_layout.takeAt(0)
            widget: QWidget | None = item.widget()
            if widget is not None:
                widget.deleteLater()


if __name__ == "__main__":
    app: QApplication = QApplication(sys.argv)
    window: MainWindow = MainWindow()
    window.show()
    sys.exit(app.exec())
