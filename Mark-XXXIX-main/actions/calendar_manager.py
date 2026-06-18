"""
calendar_manager.py
────────────────────
Aegis ke liye local calendar / schedule manager.
Events JSON mein store hote hain, voice se add/view/delete kar sako.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt6.QtGui  import QColor, QFont, QBrush
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QHBoxLayout, QLabel,
        QScrollArea, QVBoxLayout, QWidget, QPushButton, QFrame,
    )
    _QT_OK = True
except ImportError:
    _QT_OK = False

# ── Storage ───────────────────────────────────────────────────────────────────
def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    d = base / "memory" / "calendar"
    d.mkdir(parents=True, exist_ok=True)
    return d

EVENTS_FILE = _data_dir() / "events.json"

def _load_events() -> list[dict]:
    try:
        if EVENTS_FILE.exists():
            return json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_events(events: list[dict]):
    EVENTS_FILE.write_text(
        json.dumps(events, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

# ── Date parsing ──────────────────────────────────────────────────────────────
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

def _parse_date(date_str: str) -> str:
    """Returns YYYY-MM-DD. date_str can be today/tomorrow/YYYY-MM-DD/etc."""
    s = date_str.strip().lower()
    today = datetime.now().date()
    if s in ("today", "aaj"):
        return str(today)
    if s in ("tomorrow", "kal"):
        return str(today + timedelta(days=1))
    if s in ("day after tomorrow", "parso"):
        return str(today + timedelta(days=2))
    # Try YYYY-MM-DD directly
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return str(today)

def _format_time(t: str) -> str:
    """Normalize time to HH:MM"""
    t = t.strip()
    try:
        if ":" in t:
            h, m = t.split(":")
            return f"{int(h):02d}:{int(m.split()[0]):02d}"
        return f"{int(t):02d}:00"
    except Exception:
        return "00:00"

# ── PyQt6 calendar popup ──────────────────────────────────────────────────────
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

def _show_calendar_window(events: list[dict], filter_date: str | None = None):
    if not _QT_OK:
        return
    app = QApplication.instance()
    if not app:
        return

    global _active_dialog
    _active_dialog = QDialog()
    dialog = _active_dialog
    dialog.setWindowTitle("📅  Aegis — Calendar & Schedule")
    dialog.setMinimumSize(720, 500)
    dialog.setStyleSheet("background: #00060a;")

    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # Header
    hdr = QWidget()
    hdr.setFixedHeight(50)
    hdr.setStyleSheet("background: #010d14; border-bottom: 2px solid #00d4ff;")
    hlay = QHBoxLayout(hdr)
    hlay.setContentsMargins(16, 0, 16, 0)
    t = QLabel("📅  SCHEDULE — J.A.R.V.I.S")
    t.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
    t.setStyleSheet("color: #00d4ff; background: transparent;")
    hlay.addWidget(t)
    hlay.addStretch()
    sub = QLabel(datetime.now().strftime("%A, %d %B %Y"))
    sub.setFont(QFont("Courier New", 8))
    sub.setStyleSheet("color: #3a8a9a; background: transparent;")
    hlay.addWidget(sub)
    root.addWidget(hdr)

    # Scroll area
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet(
        "QScrollArea { border: none; background: #00060a; }"
        "QScrollBar:vertical { background: #000d14; width: 6px; border: none; }"
        "QScrollBar::handle:vertical { background: #1a5c7a; border-radius: 3px; }"
    )
    content = QWidget()
    content.setStyleSheet("background: #00060a;")
    clay = QVBoxLayout(content)
    clay.setContentsMargins(12, 12, 12, 12)
    clay.setSpacing(6)

    # Group by date
    today_str = str(datetime.now().date())
    grouped: dict[str, list[dict]] = {}
    for ev in sorted(events, key=lambda x: (x.get("date",""), x.get("time",""))):
        d = ev.get("date", "?")
        if filter_date and d != filter_date:
            continue
        grouped.setdefault(d, []).append(ev)

    if not grouped:
        empty = QLabel("No events scheduled.")
        empty.setFont(QFont("Courier New", 11))
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color: #3a8a9a; background: transparent; padding: 40px;")
        clay.addWidget(empty)
    else:
        for date_key in sorted(grouped.keys()):
            is_today = (date_key == today_str)
            # Date header
            try:
                d_obj = datetime.strptime(date_key, "%Y-%m-%d")
                d_label = d_obj.strftime("%A, %d %B %Y")
            except Exception:
                d_label = date_key

            d_hdr = QLabel(f"{'▶  TODAY — ' if is_today else '◈  '}{d_label}")
            d_hdr.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
            d_hdr.setStyleSheet(
                f"color: {'#00ff88' if is_today else '#ffcc00'}; "
                "background: transparent; padding: 4px 0px;"
            )
            clay.addWidget(d_hdr)

            for ev in grouped[date_key]:
                card = QWidget()
                card.setStyleSheet(
                    f"background: {'#001a10' if is_today else '#011520'}; "
                    f"border: 1px solid {'#00ff88' if is_today else '#0d3347'}; "
                    "border-radius: 5px;"
                )
                cl = QHBoxLayout(card)
                cl.setContentsMargins(12, 8, 12, 8)
                cl.setSpacing(12)

                time_lbl = QLabel(ev.get("time", "--:--"))
                time_lbl.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
                time_lbl.setFixedWidth(55)
                time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                time_lbl.setStyleSheet(
                    "color: #00060a; background: #00d4ff; "
                    "border-radius: 3px; padding: 2px;"
                )
                cl.addWidget(time_lbl)

                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet("color: #0d3347;")
                cl.addWidget(sep)

                info = QVBoxLayout()
                info.setSpacing(2)
                title_l = QLabel(ev.get("title", "Event"))
                title_l.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
                title_l.setStyleSheet("color: #d8f8ff; background: transparent;")
                info.addWidget(title_l)
                if ev.get("note"):
                    note_l = QLabel(ev["note"])
                    note_l.setFont(QFont("Courier New", 8))
                    note_l.setStyleSheet("color: #5ab8cc; background: transparent;")
                    info.addWidget(note_l)
                cl.addLayout(info, stretch=1)

                clay.addWidget(card)

            # Spacer between dates
            clay.addSpacing(8)

    clay.addStretch()
    scroll.setWidget(content)
    root.addWidget(scroll, stretch=1)

    # Footer
    ftr = QWidget()
    ftr.setFixedHeight(36)
    ftr.setStyleSheet("background: #000d14; border-top: 1px solid #0d3347;")
    flay = QHBoxLayout(ftr)
    flay.setContentsMargins(12, 0, 12, 0)
    info_l = QLabel(f"Total events: {len(events)}  ·  J.A.R.V.I.S Calendar")
    info_l.setFont(QFont("Courier New", 7))
    info_l.setStyleSheet("color: #3a8a9a; background: transparent;")
    flay.addWidget(info_l)
    flay.addStretch()
    close_btn = QPushButton("✕  CLOSE")
    close_btn.setFixedSize(80, 24)
    close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    close_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #ff3355;"
        "border: 1px solid #ff3355; border-radius: 3px; }"
        "QPushButton:hover { background: #140008; }"
    )
    close_btn.clicked.connect(dialog.close)
    flay.addWidget(close_btn)
    root.addWidget(ftr)

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


# ── Main function ─────────────────────────────────────────────────────────────
def calendar_manager(parameters: dict, player=None) -> str:
    action = parameters.get("action", "view").lower()
    events = _load_events()
    today  = str(datetime.now().date())

    # ── ADD ──────────────────────────────────────────────────────────────────
    if action == "add":
        title = parameters.get("title", "Event")
        date  = _parse_date(parameters.get("date", today))
        time  = _format_time(parameters.get("time", "00:00"))
        note  = parameters.get("note", "")
        new_ev = {"title": title, "date": date, "time": time, "note": note}
        events.append(new_ev)
        _save_events(events)
        if player:
            player.write_log(f"SYS: Event added — {title} on {date} at {time}")
        return f"Event '{title}' added on {date} at {time}."

    # ── VIEW / TODAY / TOMORROW ───────────────────────────────────────────────
    if action in ("view", "today", "show"):
        filter_d = today if action == "today" else None
        if _QT_OK:
            _run_in_main(lambda: _show_calendar_window(events, filter_d))
        today_evs = [e for e in events if e.get("date") == today]
        if not today_evs:
            return "No events today. Calendar window opened."
        summary = ", ".join(f"{e['time']} {e['title']}" for e in today_evs[:4])
        return f"Today's events: {summary}. Calendar window opened."

    # ── LIST (text only) ──────────────────────────────────────────────────────
    if action == "list":
        date_filter = parameters.get("date")
        if date_filter:
            date_filter = _parse_date(date_filter)
        relevant = [e for e in events if not date_filter or e.get("date") == date_filter]
        if not relevant:
            return "No events found."
        lines = [f"{e.get('date')} {e.get('time')} — {e.get('title')}" for e in relevant[:8]]
        return "Upcoming events:\n" + "\n".join(lines)

    # ── DELETE ────────────────────────────────────────────────────────────────
    if action == "delete":
        title_kw = parameters.get("title", "").lower()
        date_kw  = _parse_date(parameters.get("date", "")) if parameters.get("date") else None
        before   = len(events)
        events   = [
            e for e in events
            if not (
                title_kw in e.get("title", "").lower()
                and (not date_kw or e.get("date") == date_kw)
            )
        ]
        _save_events(events)
        removed = before - len(events)
        return f"Removed {removed} event(s)."

    # ── UPCOMING (next 7 days) ────────────────────────────────────────────────
    if action == "upcoming":
        end = str((datetime.now() + timedelta(days=7)).date())
        upcoming = [e for e in events if today <= e.get("date", "") <= end]
        upcoming.sort(key=lambda x: (x.get("date",""), x.get("time","")))
        if _QT_OK:
            _run_in_main(lambda: _show_calendar_window(upcoming))
        if not upcoming:
            return "No upcoming events in the next 7 days."
        lines = [f"{e.get('date')} {e.get('time')} — {e.get('title')}" for e in upcoming[:5]]
        return "Upcoming 7 days:\n" + "\n".join(lines)

    return "Calendar action not recognized. Use: add, view, today, list, delete, upcoming."
