"""
src/ui/search_dialog.py - Local Fulltext & Formula Archive Search Modal.
Enables real-time instant search across all past session notes in ~/.chalk/sessions/,
the local Notes directory, and the user's Obsidian Vault.
Jumps directly to note sections and interactive audio scrubbing timestamps.
Zero emojis, strict Dark Titanium palette.
"""

import os
import re
import html
from dataclasses import dataclass
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QFrame,
)

from src.engine.config import get_obsidian_vault_path


def parse_audio_timestamp(url_or_str: str) -> float:
    """
    Parses 'chalk-audio://01:24:15', '01:24:15', '24:15', or raw seconds into float.
    """
    s = str(url_or_str).strip()
    if s.lower().startswith("chalk-audio://"):
        s = s[len("chalk-audio://"):]
    s = s.strip("/")
    if not s:
        return 0.0

    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 3:
                return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]))
            elif len(parts) == 2:
                return float(int(parts[0]) * 60 + float(parts[1]))
            elif len(parts) == 1:
                return float(parts[0])
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


@dataclass
class SearchResult:
    file_path: str
    session_title: str
    line_number: int
    match_snippet: str
    timestamp_str: Optional[str]
    timestamp_sec: Optional[float]


def search_archive(query: str, extra_dirs: Optional[List[str]] = None) -> List[SearchResult]:
    """
    Searches local session archives, Notes/, and Obsidian vault for matching text or formulas.
    Returns list of SearchResult items ranked by relevance.
    """
    if not query or len(query.strip()) < 2:
        return []

    clean_q = query.strip().lower()
    results: List[SearchResult] = []

    search_roots = [
        os.path.expanduser("~/.chalk/sessions"),
        os.path.abspath("Notes"),
    ]
    vault = get_obsidian_vault_path()
    if vault and os.path.exists(vault):
        search_roots.append(vault)

    if extra_dirs:
        for d in extra_dirs:
            if d and os.path.exists(d):
                search_roots.append(d)

    seen_files = set()
    candidate_files = []

    for root_dir in search_roots:
        if not os.path.exists(root_dir):
            continue
        for root, _, files in os.walk(root_dir):
            for f in files:
                if f.endswith(".md") or f.endswith(".txt"):
                    fpath = os.path.join(root, f)
                    if fpath not in seen_files:
                        seen_files.add(fpath)
                        candidate_files.append(fpath)

    timestamp_regex = re.compile(r"\[?([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\]?")

    for fpath in candidate_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            doc_title = os.path.basename(fpath)
            for idx, line in enumerate(lines[:10]):
                if line.startswith("# "):
                    doc_title = line[2:].strip()
                    break

            for line_no, line in enumerate(lines, start=1):
                line_lower = line.lower()
                if clean_q in line_lower:
                    ts_str = None
                    ts_sec = None
                    ts_match = timestamp_regex.search(line)
                    if ts_match:
                        ts_str = ts_match.group(1)
                        try:
                            ts_sec = parse_audio_timestamp(ts_str)
                        except Exception:
                            ts_sec = None

                    snippet = line.strip()
                    if len(snippet) > 160:
                        snippet = snippet[:157] + "..."

                    results.append(SearchResult(
                        file_path=fpath,
                        session_title=doc_title,
                        line_number=line_no,
                        match_snippet=snippet,
                        timestamp_str=ts_str,
                        timestamp_sec=ts_sec,
                    ))

                    if len(results) >= 60:
                        return results
        except Exception:
            continue

    return results


SEARCH_MODAL_STYLESHEET = """
QDialog {
    background-color: #121317;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
}
QLabel {
    color: #94A3B8;
    font-size: 13px;
}
QLineEdit {
    background-color: #1A1C23;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 14px;
}
QLineEdit:focus {
    border: 1px solid rgba(255, 255, 255, 0.35);
    background-color: #22252F;
}
QListWidget {
    background-color: #15161B;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    background: transparent;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 6px;
    padding: 8px 10px;
    margin: 2px 0;
}
QListWidget::item:hover {
    background-color: #1E2029;
}
QListWidget::item:selected {
    background-color: #252834;
    border: 1px solid rgba(255, 255, 255, 0.2);
}
QPushButton {
    background-color: #1A1C23;
    color: #E2E8F0;
    font-size: 12px;
    font-weight: 500;
    border-radius: 6px;
    padding: 7px 14px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}
QPushButton:hover {
    background-color: #22252F;
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.25);
}
QPushButton#primaryBtn {
    background-color: #FFFFFF;
    color: #0A0A0C;
    font-weight: 600;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #E2E8F0;
}
"""


class SessionArchiveSearchDialog(QDialog):
    """
    Spotlight-style archive search modal for Chalk session notes and formulas.
    """
    result_selected = pyqtSignal(str, float)  # file_path, timestamp_sec

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chalk — Archiv- & Formelsuche (Alt+F)")
        self.setFixedSize(680, 520)
        self.setStyleSheet(SEARCH_MODAL_STYLESHEET)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self.current_results: List[SearchResult] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title_lbl = QLabel("Archiv- & Formelsuche")
        title_lbl.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: 700;")
        header.addWidget(title_lbl)

        header.addStretch()
        hint_lbl = QLabel("Echtzeit-Treffer in ~/.chalk/sessions/ & Obsidian")
        hint_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        header.addWidget(hint_lbl)
        layout.addLayout(header)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Formel, Stichwort, Theorem oder Zeitstempel suchen (z. B. 'Bayes', 'E=mc^2', '[14:20]')...")
        self.search_input.textChanged.connect(self._on_search_query_changed)
        self.search_input.returnPressed.connect(self._open_selected_result)
        layout.addWidget(self.search_input)

        # Results List
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(lambda _: self._open_selected_result())
        layout.addWidget(self.results_list)

        # Status & Action Bar
        action_bar = QHBoxLayout()
        self.status_lbl = QLabel("Geben Sie mindestens 2 Zeichen ein.")
        self.status_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        action_bar.addWidget(self.status_lbl)

        action_bar.addStretch()

        self.btn_open_external = QPushButton("Im Editor öffnen")
        self.btn_open_external.clicked.connect(self._open_in_editor)
        action_bar.addWidget(self.btn_open_external)

        self.btn_open_hud = QPushButton("In Notizen laden")
        self.btn_open_hud.setObjectName("primaryBtn")
        self.btn_open_hud.clicked.connect(self._open_selected_result)
        action_bar.addWidget(self.btn_open_hud)

        layout.addLayout(action_bar)

    def _on_search_query_changed(self, text: str):
        query = text.strip()
        self.results_list.clear()
        self.current_results = []

        if len(query) < 2:
            self.status_lbl.setText("Geben Sie mindestens 2 Zeichen ein.")
            return

        self.current_results = search_archive(query)
        if not self.current_results:
            self.status_lbl.setText("Keine Treffer gefunden.")
            return

        self.status_lbl.setText(f"{len(self.current_results)} Treffer gefunden.")

        for idx, res in enumerate(self.current_results):
            item = QListWidgetItem(self.results_list)
            widget = self._create_result_widget(res, query)
            item.setSizeHint(widget.sizeHint())
            self.results_list.addItem(item)
            self.results_list.setItemWidget(item, widget)

        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)

    def _create_result_widget(self, res: SearchResult, query: str) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 3, 4, 3)
        vbox.setSpacing(3)

        # Title row
        title_row = QHBoxLayout()
        doc_lbl = QLabel(res.session_title)
        doc_lbl.setStyleSheet("color: #FFFFFF; font-weight: 600; font-size: 13px;")
        title_row.addWidget(doc_lbl)

        if res.timestamp_str:
            ts_lbl = QLabel(f"[{res.timestamp_str}]")
            ts_lbl.setStyleSheet(
                "color: #38BDF8; font-family: ui-monospace, monospace; "
                "font-weight: 700; font-size: 11px; background: rgba(56, 189, 248, 0.12); "
                "padding: 1px 6px; border-radius: 4px;"
            )
            title_row.addWidget(ts_lbl)

        title_row.addStretch()

        file_name = os.path.basename(res.file_path)
        loc_lbl = QLabel(f"{file_name}:{res.line_number}")
        loc_lbl.setStyleSheet("color: #64748B; font-size: 10px; font-family: monospace;")
        title_row.addWidget(loc_lbl)

        vbox.addLayout(title_row)

        # Highlight snippet
        escaped_snip = html.escape(res.match_snippet)
        escaped_q = html.escape(query)
        highlighted = re.sub(
            re.escape(escaped_q),
            f"<span style='background-color: rgba(255, 255, 255, 0.25); color: #FFFFFF; font-weight: bold;'>{escaped_q}</span>",
            escaped_snip,
            flags=re.IGNORECASE,
        )

        snip_lbl = QLabel()
        snip_lbl.setTextFormat(Qt.TextFormat.RichText)
        snip_lbl.setText(highlighted)
        snip_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")
        vbox.addWidget(snip_lbl)

        return container

    def _open_selected_result(self):
        row = self.results_list.currentRow()
        if 0 <= row < len(self.current_results):
            res = self.current_results[row]
            sec = res.timestamp_sec if res.timestamp_sec is not None else 0.0
            self.result_selected.emit(res.file_path, sec)
            self.accept()

    def _open_in_editor(self):
        row = self.results_list.currentRow()
        if 0 <= row < len(self.current_results):
            res = self.current_results[row]
            if os.path.exists(res.file_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(res.file_path))
