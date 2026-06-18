"""
study_explainer.py
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Jab user kuch study-related poochhe, Aegis ek visual diagram +
main points wala popup window dikhata hai.
"""

from __future__ import annotations

import io
import textwrap
import threading
from pathlib import Path

# â”€â”€ PIL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# â”€â”€ PyQt6 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal
    from PyQt6.QtGui  import QColor, QFont, QPixmap, QPainter, QBrush, QPen
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QHBoxLayout, QLabel,
        QScrollArea, QTextEdit, QVBoxLayout, QWidget, QPushButton,
    )
    _QT_OK = True
except ImportError:
    _QT_OK = False

_active_dialog = None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Colour palette (Aegis dark theme se match)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BG      = (0,   6,  10)
PANEL   = (1,  13,  20)
BORDER  = (13, 51,  71)
PRI     = (0, 212, 255)
ACC     = (255, 107, 0)
ACC2    = (255, 204, 0)
GREEN   = (0, 255, 136)
WHITE   = (216, 248, 255)
TEXT    = (143, 252, 255)
DIM     = (58, 138, 154)

# Icons per category
_ICON_MAP = {
    "biology":    "ðŸ§¬", "chemistry": "âš—ï¸",  "physics":   "âš›ï¸",
    "math":       "ðŸ“", "history":   "ðŸ“œ",  "geography": "ðŸŒ",
    "computer":   "ðŸ’»", "economics": "ðŸ“Š",  "english":   "ðŸ“–",
    "science":    "ðŸ”¬", "general":   "ðŸ“š",  "default":   "ðŸŽ“",
}

def _detect_icon(topic: str) -> str:
    t = topic.lower()
    for key, icon in _ICON_MAP.items():
        if key in t:
            return icon
    return _ICON_MAP["default"]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  PIL se diagram image banana
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _make_diagram_image(topic: str, points: list[str], explanation: str) -> bytes | None:
    """PIL se ek dark-themed diagram PNG banata hai aur bytes return karta hai."""
    if not _PIL_OK:
        return None

    W, H = 760, 480 + max(0, len(points) - 5) * 36

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # â”€â”€ helper to load font â”€â”€
    def _font(size: int, bold: bool = False):
        candidates = []
        if bold:
            candidates = [
                "C:/Windows/Fonts/courbd.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/seguisb.ttf",
            ]
        else:
            candidates = [
                "C:/Windows/Fonts/cour.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
        for p in candidates:
            if Path(p).exists():
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    fnt_title  = _font(26, bold=True)
    fnt_head   = _font(17, bold=True)
    fnt_body   = _font(14)
    fnt_small  = _font(11)

    icon = _detect_icon(topic)

    # â”€â”€ border glow â”€â”€
    draw.rectangle([2, 2, W-3, H-3], outline=(0, 80, 110), width=2)
    draw.rectangle([5, 5, W-6, H-6], outline=(0, 40, 60),  width=1)

    # â”€â”€ header bar â”€â”€
    draw.rectangle([0, 0, W, 72], fill=(1, 18, 28))
    draw.line([(0, 72), (W, 72)], fill=PRI, width=2)

    # title
    draw.text((20, 12), f"{icon}  {topic}", font=fnt_title, fill=PRI)
    draw.text((20, 50), "Study Explainer  Â·  J.A.R.V.I.S", font=fnt_small, fill=DIM)

    # â”€â”€ corner brackets â”€â”€
    L = 18
    for bx, by, dx, dy in [(0,0,1,1),(W-1,0,-1,1),(0,H-1,1,-1),(W-1,H-1,-1,-1)]:
        draw.line([(bx, by), (bx+dx*L, by)],   fill=PRI, width=2)
        draw.line([(bx, by), (bx, by+dy*L)],   fill=PRI, width=2)

    # â”€â”€ explanation box â”€â”€
    y = 90
    draw.rectangle([14, y, W-14, y+5], fill=(0, 50, 80))  # accent bar
    y += 14
    draw.text((20, y), "â—ˆ  EXPLANATION", font=fnt_head, fill=ACC2)
    y += 26

    # wrap explanation
    max_chars = 88
    wrapped = textwrap.wrap(explanation or "Explanation not provided.", width=max_chars)
    for line in wrapped[:5]:   # max 5 lines
        draw.text((20, y), line, font=fnt_body, fill=WHITE)
        y += 22
    y += 10

    # â”€â”€ divider â”€â”€
    draw.line([(14, y), (W-14, y)], fill=BORDER, width=1)
    y += 14

    # â”€â”€ main points â”€â”€
    draw.text((20, y), "â—‰  KEY POINTS", font=fnt_head, fill=GREEN)
    y += 26

    for i, pt in enumerate(points):
        # bullet circle
        bx, by = 26, y + 8
        draw.ellipse([bx-5, by-5, bx+5, by+5], fill=PRI, outline=None)
        draw.ellipse([bx-3, by-3, bx+3, by+3], fill=BG,  outline=None)

        # text â€” wrap long points
        pt_wrapped = textwrap.wrap(pt, width=82)
        for j, pline in enumerate(pt_wrapped[:2]):
            col = WHITE if j == 0 else DIM
            draw.text((40, y + j*18), pline, font=fnt_body, fill=col)
        y += 36 + (len(pt_wrapped) - 1) * 18
        y = min(y, H - 60)   # clamp

    # â”€â”€ bottom bar â”€â”€
    draw.rectangle([0, H-28, W, H], fill=(1, 13, 18))
    draw.line([(0, H-28), (W, H-28)], fill=BORDER, width=1)
    draw.text((W//2 - 100, H-20),
              "J.A.R.V.I.S  Â·  STUDY MODULE  Â·  MARK XXXIX",
              font=fnt_small, fill=DIM)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  PyQt6 Popup window
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _show_study_window(topic: str, points: list[str],
                       explanation: str, img_bytes: bytes | None):
    """Main thread mein PyQt6 popup window dikhata hai."""
    if not _QT_OK:
        return

    app = QApplication.instance()
    if not app:
        return   # QApplication nahi hai â€” skip

    global _active_dialog
    _active_dialog = QDialog()
    dialog = _active_dialog
    dialog.setWindowTitle(f"ðŸ“š  Study Explainer â€” {topic}")
    dialog.setMinimumSize(820, 620)
    dialog.setStyleSheet("background: #00060a; color: #8ffcff;")

    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # â”€â”€ header â”€â”€
    hdr = QWidget()
    hdr.setFixedHeight(48)
    hdr.setStyleSheet(
        "background: #010d14; border-bottom: 2px solid #00d4ff;"
    )
    hlay = QHBoxLayout(hdr)
    hlay.setContentsMargins(16, 0, 16, 0)

    icon = _detect_icon(topic)
    htitle = QLabel(f"{icon}  {topic.upper()}")
    htitle.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
    htitle.setStyleSheet("color: #00d4ff; background: transparent;")
    hlay.addWidget(htitle)
    hlay.addStretch()

    badge = QLabel("â—ˆ STUDY EXPLAINER")
    badge.setFont(QFont("Courier New", 8))
    badge.setStyleSheet("color: #3a8a9a; background: transparent;")
    hlay.addWidget(badge)
    root.addWidget(hdr)

    # â”€â”€ body (image + points) â”€â”€
    body = QHBoxLayout()
    body.setContentsMargins(10, 10, 10, 10)
    body.setSpacing(10)

    # left: diagram image
    if img_bytes:
        px = QPixmap()
        px.loadFromData(img_bytes)
        img_lbl = QLabel()
        img_lbl.setPixmap(
            px.scaled(500, 450,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
        )
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        img_lbl.setStyleSheet(
            "border: 1px solid #0d3347; border-radius: 4px; background: #010d14; padding:4px;"
        )
        body.addWidget(img_lbl, stretch=3)

    # right: main points panel
    right = QWidget()
    right.setStyleSheet(
        "background: #010f18; border: 1px solid #0d3347; border-radius: 4px;"
    )
    rlay = QVBoxLayout(right)
    rlay.setContentsMargins(12, 12, 12, 12)
    rlay.setSpacing(8)

    ptitle = QLabel("â—‰  KEY POINTS")
    ptitle.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
    ptitle.setStyleSheet("color: #00ff88; background: transparent;")
    rlay.addWidget(ptitle)

    sep = QWidget(); sep.setFixedHeight(1)
    sep.setStyleSheet("background: #0d3347;")
    rlay.addWidget(sep)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet(
        "QScrollArea { border: none; background: transparent; }"
        "QScrollBar:vertical { background: #000d14; width: 6px; border: none; }"
        "QScrollBar::handle:vertical { background: #1a5c7a; border-radius: 3px; }"
    )

    pts_widget = QWidget()
    pts_widget.setStyleSheet("background: transparent;")
    pts_lay = QVBoxLayout(pts_widget)
    pts_lay.setContentsMargins(0, 0, 0, 0)
    pts_lay.setSpacing(6)

    for i, pt in enumerate(points, 1):
        row = QWidget()
        row.setStyleSheet(
            "background: #011520; border: 1px solid #0d3347; border-radius: 4px;"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 6, 8, 6)
        rl.setSpacing(8)

        num_lbl = QLabel(f"{i:02d}")
        num_lbl.setFixedWidth(26)
        num_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num_lbl.setStyleSheet(
            "color: #00060a; background: #00d4ff; border-radius: 3px;"
        )
        rl.addWidget(num_lbl)

        pt_lbl = QLabel(pt)
        pt_lbl.setWordWrap(True)
        pt_lbl.setFont(QFont("Courier New", 9))
        pt_lbl.setStyleSheet("color: #d8f8ff; background: transparent;")
        rl.addWidget(pt_lbl, stretch=1)
        pts_lay.addWidget(row)

    pts_lay.addStretch()
    scroll.setWidget(pts_widget)
    rlay.addWidget(scroll, stretch=1)

    # explanation box at bottom
    exp_title = QLabel("â—ˆ  EXPLANATION")
    exp_title.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
    exp_title.setStyleSheet("color: #ffcc00; background: transparent;")
    rlay.addWidget(exp_title)

    exp_box = QTextEdit()
    exp_box.setReadOnly(True)
    exp_box.setPlainText(explanation or "")
    exp_box.setFont(QFont("Courier New", 8))
    exp_box.setFixedHeight(90)
    exp_box.setStyleSheet(
        "QTextEdit { background: #000d14; color: #8ffcff; "
        "border: 1px solid #0d3347; border-radius: 3px; padding: 4px; }"
        "QScrollBar:vertical { width: 6px; background: #000d14; }"
        "QScrollBar::handle:vertical { background: #1a5c7a; border-radius: 3px; }"
    )
    rlay.addWidget(exp_box)

    body.addWidget(right, stretch=2)
    root.addLayout(body, stretch=1)

    # â”€â”€ footer â”€â”€
    ftr = QWidget()
    ftr.setFixedHeight(36)
    ftr.setStyleSheet(
        "background: #000d14; border-top: 1px solid #0d3347;"
    )
    flay = QHBoxLayout(ftr)
    flay.setContentsMargins(12, 0, 12, 0)

    info = QLabel("J.A.R.V.I.S  Â·  STUDY MODULE  Â·  MARK XXXIX")
    info.setFont(QFont("Courier New", 7))
    info.setStyleSheet("color: #3a8a9a; background: transparent;")
    flay.addWidget(info)
    flay.addStretch()

    close_btn = QPushButton("âœ•  CLOSE")
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Main entry point
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def study_explainer(parameters: dict, player=None, speak=None) -> str:
    """
    Aegis study explainer tool.

    parameters keys:
        topic       â€“ kya explain karna hai
        explanation â€“ short paragraph explanation
        points      â€“ list of key points (strings)
    """
    topic       = parameters.get("topic", "Topic")
    explanation = parameters.get("explanation", "")
    points_raw  = parameters.get("points", [])

    # points can come as list or newline-separated string
    if isinstance(points_raw, str):
        points = [p.strip() for p in points_raw.split("\n") if p.strip()]
    else:
        points = [str(p).strip() for p in points_raw if str(p).strip()]

    if not points:
        points = ["No key points provided."]

    # PIL diagram
    img_bytes = None
    if _PIL_OK:
        try:
            img_bytes = _make_diagram_image(topic, points, explanation)
        except Exception as e:
            print(f"[StudyExplainer] PIL error: {e}")

    # PyQt6 popup â€” Qt widget sirf main thread mein!
    if _QT_OK:
        app = QApplication.instance()
        if app:
            QTimer.singleShot(
                0,
                lambda: _show_study_window(topic, points, explanation, img_bytes)
            )

    if player:
        try:
            player.write_log(f"SYS: Study panel opened â€” {topic}")
        except Exception:
            pass

    return (
        f"Study panel displayed for '{topic}'. "
        f"Now explain this topic to the user clearly using the key points."
    )

