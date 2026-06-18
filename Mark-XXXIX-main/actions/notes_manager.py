"""
notes_manager.py
─────────────────
Aegis ke liye voice notes + journal system.
Notes markdown files mein save hote hain, search + view kar sako.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt6.QtGui  import QFont, QColor
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QHBoxLayout, QLabel,
        QScrollArea, QVBoxLayout, QWidget, QPushButton,
        QTextEdit, QLineEdit, QFrame,
    )
    _QT_OK = True
except ImportError:
    _QT_OK = False


# ── Storage ───────────────────────────────────────────────────────────────────
def _notes_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    d = base / "memory" / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d

NOTES_FILE = _notes_dir() / "notes.json"

def _load_notes() -> list[dict]:
    try:
        if NOTES_FILE.exists():
            return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_notes(notes: list[dict]):
    NOTES_FILE.write_text(
        json.dumps(notes, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

# ── Category colors ───────────────────────────────────────────────────────────
_CAT_COLORS = {
    "general":  ("#00d4ff", "#001a22"),
    "study":    ("#00ff88", "#001a10"),
    "idea":     ("#ffcc00", "#1a1400"),
    "todo":     ("#ff6b00", "#1a0a00"),
    "personal": ("#cc44ff", "#160022"),
    "work":     ("#ff3355", "#1a0008"),
}
_CAT_ICONS = {
    "general": "📌", "study": "📚", "idea": "💡",
    "todo": "✅", "personal": "👤", "work": "💼",
}

def _detect_category(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["study", "padh", "exam", "notes", "learn"]):
        return "study"
    if any(w in t for w in ["idea", "soch", "plan", "concept"]):
        return "idea"
    if any(w in t for w in ["karna hai", "todo", "task", "reminder", "do this"]):
        return "todo"
    if any(w in t for w in ["work", "meeting", "client", "project", "deadline"]):
        return "work"
    if any(w in t for w in ["personal", "private", "diary", "feel"]):
        return "personal"
    return "general"


# ── PyQt6 Notes window ────────────────────────────────────────────────────────
_active_dialog = None

class _CallProxy(QObject if _QT_OK else object):
    if _QT_OK:
        sig = pyqtSignal(object)
    def __init__(self):
        super().__init__()
        if _QT_OK:
            self.sig.connect(self._run)
    def _run(self, f):
        f()

_proxy = None

def _run_in_main(func):
    if not _QT_OK:
        return
    app = QApplication.instance()
    if not app:
        return
    global _proxy
    if _proxy is None:
        _proxy = _CallProxy()
        _proxy.moveToThread(app.thread())
    _proxy.sig.emit(func)

def _show_notes_window(notes: list[dict], highlight_id: int | None = None):
    if not _QT_OK:
        return
    app = QApplication.instance()
    if not app:
        return

    global _active_dialog
    _active_dialog = QDialog()
    dialog = _active_dialog
    dialog.setWindowTitle("📝  Aegis — Notes & Journal")
    dialog.setMinimumSize(800, 560)
    dialog.setStyleSheet("background: #00060a;")

    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # Header
    hdr = QWidget()
    hdr.setFixedHeight(50)
    hdr.setStyleSheet("background: #010d14; border-bottom: 2px solid #ffcc00;")
    hlay = QHBoxLayout(hdr)
    hlay.setContentsMargins(16, 0, 16, 0)
    t = QLabel("📝  NOTES — J.A.R.V.I.S")
    t.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
    t.setStyleSheet("color: #ffcc00; background: transparent;")
    hlay.addWidget(t)
    hlay.addStretch()
    count_l = QLabel(f"{len(notes)} note(s)")
    count_l.setFont(QFont("Courier New", 8))
    count_l.setStyleSheet("color: #3a8a9a; background: transparent;")
    hlay.addWidget(count_l)
    root.addWidget(hdr)

    # Body: left = list, right = detail
    body = QHBoxLayout()
    body.setContentsMargins(8, 8, 8, 8)
    body.setSpacing(8)

    # Left panel — note cards
    left = QWidget()
    left.setStyleSheet("background: transparent;")
    left_lay = QVBoxLayout(left)
    left_lay.setContentsMargins(0, 0, 0, 0)
    left_lay.setSpacing(5)

    scroll_l = QScrollArea()
    scroll_l.setWidgetResizable(True)
    scroll_l.setFixedWidth(260)
    scroll_l.setStyleSheet(
        "QScrollArea { border: none; background: transparent; }"
        "QScrollBar:vertical { background: #000d14; width: 5px; border: none; }"
        "QScrollBar::handle:vertical { background: #1a5c7a; border-radius: 2px; }"
    )
    list_widget = QWidget()
    list_widget.setStyleSheet("background: transparent;")
    list_lay = QVBoxLayout(list_widget)
    list_lay.setContentsMargins(0, 0, 0, 0)
    list_lay.setSpacing(4)

    # Right panel — note detail
    detail_box = QTextEdit()
    detail_box.setReadOnly(True)
    detail_box.setFont(QFont("Courier New", 10))
    detail_box.setStyleSheet(
        "QTextEdit { background: #010f18; color: #d8f8ff; "
        "border: 1px solid #0d3347; border-radius: 4px; padding: 12px; }"
        "QScrollBar:vertical { width: 5px; background: #000d14; }"
        "QScrollBar::handle:vertical { background: #1a5c7a; border-radius: 2px; }"
    )

    def _show_note(note: dict):
        cat   = note.get("category", "general")
        icon  = _CAT_ICONS.get(cat, "📌")
        ts    = note.get("timestamp", "")
        title = note.get("title", "Note")
        body_txt = note.get("body", "")
        detail_box.setPlainText(
            f"{icon}  {title}\n"
            f"{'─' * 50}\n"
            f"Category : {cat.upper()}\n"
            f"Date     : {ts}\n"
            f"{'─' * 50}\n\n"
            f"{body_txt}"
        )

    sorted_notes = sorted(notes, key=lambda x: x.get("timestamp", ""), reverse=True)

    for i, note in enumerate(sorted_notes):
        cat  = note.get("category", "general")
        fg, bg = _CAT_COLORS.get(cat, ("#00d4ff", "#001a22"))
        icon = _CAT_ICONS.get(cat, "📌")
        card = QPushButton(f"{icon}  {note.get('title','Note')[:28]}")
        card.setFont(QFont("Courier New", 9))
        card.setFixedHeight(38)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        is_highlight = (i == 0 and highlight_id is None) or (note.get("id") == highlight_id)
        card.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; "
            f"border: 1px solid {fg}; border-radius: 3px; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {bg}; border: 2px solid {fg}; }}"
        )
        note_ref = note
        card.clicked.connect(lambda _, n=note_ref: _show_note(n))
        list_lay.addWidget(card)
        if is_highlight:
            _show_note(note)

    list_lay.addStretch()
    scroll_l.setWidget(list_widget)
    body.addWidget(scroll_l)

    sep_v = QFrame()
    sep_v.setFrameShape(QFrame.Shape.VLine)
    sep_v.setStyleSheet("color: #0d3347;")
    body.addWidget(sep_v)

    body.addWidget(detail_box, stretch=1)
    root.addLayout(body, stretch=1)

    # Footer
    ftr = QWidget()
    ftr.setFixedHeight(36)
    ftr.setStyleSheet("background: #000d14; border-top: 1px solid #0d3347;")
    flay = QHBoxLayout(ftr)
    flay.setContentsMargins(12, 0, 12, 0)
    fl = QLabel("J.A.R.V.I.S  ·  NOTES MODULE  ·  Voice-powered")
    fl.setFont(QFont("Courier New", 7))
    fl.setStyleSheet("color: #3a8a9a; background: transparent;")
    flay.addWidget(fl)
    flay.addStretch()
    cb = QPushButton("✕  CLOSE")
    cb.setFixedSize(80, 24)
    cb.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
    cb.setCursor(Qt.CursorShape.PointingHandCursor)
    cb.setStyleSheet(
        "QPushButton { background: transparent; color: #ff3355;"
        "border: 1px solid #ff3355; border-radius: 3px; }"
        "QPushButton:hover { background: #140008; }"
    )
    cb.clicked.connect(dialog.close)
    flay.addWidget(cb)
    root.addWidget(ftr)

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


# ── Main function ─────────────────────────────────────────────────────────────
def notes_manager(parameters: dict, player=None) -> str:
    action = parameters.get("action", "add").lower()
    notes  = _load_notes()

    # ── ADD / SAVE ─────────────────────────────────────────────────────────────
    if action in ("add", "save", "create"):
        body_text = parameters.get("body", parameters.get("text", parameters.get("note", "")))
        title     = parameters.get("title", body_text[:40].strip() or "Quick Note")
        category  = parameters.get("category") or _detect_category(body_text)
        ts        = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_note  = {
            "id":        len(notes) + 1,
            "title":     title,
            "body":      body_text,
            "category":  category,
            "timestamp": ts,
        }
        notes.append(new_note)
        _save_notes(notes)
        if player:
            player.write_log(f"SYS: Note saved — {title}")
        if _QT_OK:
            _run_in_main(lambda: _show_notes_window(notes, new_note["id"]))
        return f"Note saved: '{title}' ({category}). Notes window opened."

    # ── VIEW / SHOW ────────────────────────────────────────────────────────────
    if action in ("view", "show", "open"):
        if _QT_OK:
            _run_in_main(lambda: _show_notes_window(notes))
        if not notes:
            return "No notes found. Notes window opened."
        return f"Notes window opened. You have {len(notes)} note(s)."

    # ── SEARCH ─────────────────────────────────────────────────────────────────
    if action == "search":
        query   = parameters.get("query", "").lower()
        results = [
            n for n in notes
            if query in n.get("title","").lower() or query in n.get("body","").lower()
        ]
        if _QT_OK:
            _run_in_main(lambda: _show_notes_window(results))
        if not results:
            return f"No notes found for '{query}'."
        return f"Found {len(results)} note(s) matching '{query}'. Window opened."

    # ── LIST ───────────────────────────────────────────────────────────────────
    if action == "list":
        if not notes:
            return "No notes saved yet."
        recent = sorted(notes, key=lambda x: x.get("timestamp",""), reverse=True)[:5]
        lines  = [f"• {n['title']} [{n['category']}] — {n['timestamp']}" for n in recent]
        return "Recent notes:\n" + "\n".join(lines)

    # ── DELETE ─────────────────────────────────────────────────────────────────
    if action == "delete":
        kw     = parameters.get("title", "").lower()
        before = len(notes)
        notes  = [n for n in notes if kw not in n.get("title","").lower()]
        _save_notes(notes)
        return f"Deleted {before - len(notes)} note(s)."

    return "Notes action not recognized. Use: add, view, search, list, delete."
