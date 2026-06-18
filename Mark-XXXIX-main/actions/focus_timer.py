"""
focus_timer.py
──────────────
Aegis Pomodoro / Focus Timer.
25 min kaam, 5 min break — sound + popup notification.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt6.QtGui  import QFont, QColor, QPainter, QPen, QBrush
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QHBoxLayout, QLabel,
        QVBoxLayout, QWidget, QPushButton,
    )
    _QT_OK = True
except ImportError:
    _QT_OK = False

try:
    import winsound
    _SOUND_OK = True
except ImportError:
    _SOUND_OK = False


# ── Timer state (global so only one runs at a time) ───────────────────────────
_active_timer: "_FocusTimer | None" = None
_timer_lock   = threading.Lock()


class _FocusTimer(QObject if _QT_OK else object):
    """Ek Pomodoro session handle karta hai."""

    if _QT_OK:
        tick_sig  = pyqtSignal(int, str)   # remaining_secs, mode
        done_sig  = pyqtSignal(str)        # message

    def __init__(self, work_min: int, break_min: int, cycles: int, speak=None):
        if _QT_OK:
            super().__init__()
        self.work_secs  = work_min * 60
        self.break_secs = break_min * 60
        self.cycles     = cycles
        self.speak      = speak
        self._stop      = threading.Event()
        self._dialog    = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _beep(self, kind: str = "start"):
        if not _SOUND_OK:
            return
        try:
            if kind == "start":
                winsound.Beep(880, 200)
                winsound.Beep(1100, 200)
            elif kind == "end":
                winsound.Beep(660, 300)
                winsound.Beep(550, 300)
                winsound.Beep(440, 500)
            elif kind == "break":
                winsound.Beep(440, 200)
                winsound.Beep(660, 400)
        except Exception:
            pass

    def _run(self):
        for cycle in range(1, self.cycles + 1):
            if self._stop.is_set():
                break

            # ── WORK phase ──
            mode = "FOCUS"
            self._beep("start")
            if self.speak:
                self.speak(
                    f"Cycle {cycle} of {self.cycles}. "
                    f"Focus mode — {self.work_secs // 60} minutes. Let's go, sir."
                )
            remaining = self.work_secs
            while remaining > 0 and not self._stop.is_set():
                if _QT_OK and hasattr(self, "tick_sig"):
                    self.tick_sig.emit(remaining, mode)
                time.sleep(1)
                remaining -= 1

            if self._stop.is_set():
                break

            self._beep("end")
            if self.speak:
                self.speak(
                    f"Work session complete! Take a {self.break_secs // 60} minute break."
                )

            if cycle == self.cycles:
                if _QT_OK and hasattr(self, "done_sig"):
                    self.done_sig.emit("All cycles complete! Well done, sir.")
                if self.speak:
                    self.speak("All focus cycles complete. Excellent work, sir!")
                break

            # ── BREAK phase ──
            mode = "BREAK"
            self._beep("break")
            remaining = self.break_secs
            while remaining > 0 and not self._stop.is_set():
                if _QT_OK and hasattr(self, "tick_sig"):
                    self.tick_sig.emit(remaining, mode)
                time.sleep(1)
                remaining -= 1

        with _timer_lock:
            global _active_timer
            _active_timer = None


# ── PyQt6 Timer Window ────────────────────────────────────────────────────────
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

def _show_timer_window(ft: _FocusTimer, work_min: int, break_min: int, cycles: int):
    if not _QT_OK:
        return
    app = QApplication.instance()
    if not app:
        return

    global _active_dialog
    _active_dialog = QDialog()
    dialog = _active_dialog
    dialog.setWindowTitle("⏱  Aegis — Focus Timer")
    dialog.setFixedSize(380, 320)
    dialog.setStyleSheet("background: #00060a;")

    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # Header
    hdr = QWidget()
    hdr.setFixedHeight(46)
    hdr.setStyleSheet("background: #010d14; border-bottom: 2px solid #00ff88;")
    hlay = QHBoxLayout(hdr)
    hlay.setContentsMargins(16, 0, 16, 0)
    ht = QLabel("⏱  FOCUS TIMER — J.A.R.V.I.S")
    ht.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
    ht.setStyleSheet("color: #00ff88; background: transparent;")
    hlay.addWidget(ht)
    root.addWidget(hdr)

    # Mode label
    mode_lbl = QLabel("● FOCUS")
    mode_lbl.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
    mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mode_lbl.setStyleSheet("color: #00d4ff; background: transparent; padding: 10px;")
    root.addWidget(mode_lbl)

    # Big timer display
    timer_lbl = QLabel(f"{work_min:02d}:00")
    timer_lbl.setFont(QFont("Courier New", 52, QFont.Weight.Bold))
    timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    timer_lbl.setStyleSheet("color: #d8f8ff; background: transparent;")
    root.addWidget(timer_lbl)

    # Info row
    info_lbl = QLabel(f"Work {work_min}m  ·  Break {break_min}m  ·  {cycles} cycles")
    info_lbl.setFont(QFont("Courier New", 8))
    info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    info_lbl.setStyleSheet("color: #3a8a9a; background: transparent; padding: 4px;")
    root.addWidget(info_lbl)

    # Stop button
    stop_btn = QPushButton("⏹  STOP TIMER")
    stop_btn.setFixedHeight(32)
    stop_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
    stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    stop_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #ff3355;"
        "border: 1px solid #ff3355; border-radius: 3px; margin: 8px 20px; }"
        "QPushButton:hover { background: #140008; }"
    )

    def _stop():
        ft.stop()
        dialog.close()

    stop_btn.clicked.connect(_stop)
    root.addWidget(stop_btn)

    # Footer
    ftr = QWidget()
    ftr.setFixedHeight(30)
    ftr.setStyleSheet("background: #000d14; border-top: 1px solid #0d3347;")
    flay = QHBoxLayout(ftr)
    flay.setContentsMargins(12, 0, 12, 0)
    fl = QLabel("J.A.R.V.I.S  ·  Pomodoro Module")
    fl.setFont(QFont("Courier New", 7))
    fl.setStyleSheet("color: #3a8a9a; background: transparent;")
    flay.addWidget(fl)
    root.addWidget(ftr)

    # Connect signals
    if hasattr(ft, "tick_sig"):
        def _on_tick(secs: int, mode: str):
            mins = secs // 60
            s    = secs % 60
            timer_lbl.setText(f"{mins:02d}:{s:02d}")
            if mode == "FOCUS":
                mode_lbl.setText("● FOCUS")
                mode_lbl.setStyleSheet("color: #00d4ff; background: transparent; padding: 10px;")
                timer_lbl.setStyleSheet("color: #d8f8ff; background: transparent;")
            else:
                mode_lbl.setText("☕ BREAK")
                mode_lbl.setStyleSheet("color: #00ff88; background: transparent; padding: 10px;")
                timer_lbl.setStyleSheet("color: #00ff88; background: transparent;")
        ft.tick_sig.connect(_on_tick)

    if hasattr(ft, "done_sig"):
        def _on_done(msg: str):
            timer_lbl.setText("DONE!")
            mode_lbl.setText("✅ COMPLETE")
            mode_lbl.setStyleSheet("color: #ffcc00; background: transparent; padding: 10px;")
            QTimer.singleShot(4000, dialog.close)
        ft.done_sig.connect(_on_done)

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


# ── Main function ─────────────────────────────────────────────────────────────
def focus_timer(parameters: dict, player=None, speak=None) -> str:
    global _active_timer

    action = parameters.get("action", "start").lower()

    # ── STOP ────────────────────────────────────────────────────────────────
    if action == "stop":
        with _timer_lock:
            if _active_timer:
                _active_timer.stop()
                _active_timer = None
                return "Focus timer stopped."
            return "No active timer to stop."

    # ── STATUS ───────────────────────────────────────────────────────────────
    if action == "status":
        with _timer_lock:
            if _active_timer:
                return "Focus timer is running."
            return "No active timer."

    # ── START ────────────────────────────────────────────────────────────────
    with _timer_lock:
        if _active_timer:
            return "A focus timer is already running. Say 'stop timer' first."

    work_min  = int(parameters.get("work_minutes",  25))
    break_min = int(parameters.get("break_minutes",  5))
    cycles    = int(parameters.get("cycles",          4))

    ft = _FocusTimer(work_min, break_min, cycles, speak=speak)

    with _timer_lock:
        _active_timer = ft

    ft.start()

    if _QT_OK:
        _run_in_main(lambda: _show_timer_window(ft, work_min, break_min, cycles))

    if player:
        player.write_log(f"SYS: Focus timer — {work_min}m work / {break_min}m break × {cycles}")

    return (
        f"Focus timer started: {work_min} minutes work, "
        f"{break_min} minutes break, {cycles} cycles. "
        f"Stay focused, sir!"
    )
