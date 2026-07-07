"""
MARK XXXIX — Sci-Fi HUD v4 (STONIC-STYLE)
3-column layout, rounded panels, spherical particle cluster,
status cards, chat panel — modern cinematic HUD.
"""
from __future__ import annotations

import functools
import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QRadialGradient, QShortcut, QTransform,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar,
)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 1440, 920
_MIN_W,     _MIN_H     = 1100, 720

_OS = platform.system()


# ==================== Stonic-style Palette ====================
class C:
    BG_DEEP    = "#060912"
    BG         = "#0a0e18"
    PANEL      = "#0e1525"
    PANEL_HI   = "#131b30"
    PANEL_DARK = "#080c18"

    BORDER     = "#1a2840"
    BORDER_HI  = "#2a3a5a"

    ACCENT     = "#00d4ff"
    ACCENT_BR  = "#5fdbff"
    AMBER      = "#ffb347"
    GOLD       = "#ffcc66"
    VIOLET     = "#a86bff"
    ROSE       = "#ff6b9d"

    TEXT       = "#ffffff"
    TEXT_DIM   = "#6a7a8a"
    TEXT_MUTED = "#3a4a5a"

    SUCCESS    = "#4ade80"
    WARNING    = "#ffaa44"
    DANGER     = "#ff3a5c"


STATE_PALETTES = {
    "INITIALISING": ("#0a4860", "#3a6a8a", "#7fb8d8", C.AMBER),
    "LISTENING":    (C.ACCENT, C.ACCENT_BR, "#e8fbff", C.SUCCESS),
    "SPEAKING":     (C.ACCENT, C.ACCENT_BR, "#e8fbff", C.AMBER),
    "THINKING":     (C.VIOLET, "#d4a8ff",  "#f0e0ff", C.VIOLET),
    "MUTED":        ("#1a3a5a", "#3a5a78", "#5a7a98", C.TEXT_DIM),
}


# ==================== Operational Modes (Dynamic Island) ====================
# Each mode defines a colour palette + animation speed. The 'standard' mode
# keeps the HUD in its default look (no dynamic island shown). Switching to
# any other mode reveals the Dynamic Island at the top of the centre column.
MODES = {
    "standard":  {"name": "STANDARD",  "primary": C.ACCENT,    "secondary": C.ACCENT_BR, "accent": "#e8fbff", "glow": C.ACCENT,    "speed": 1.0,  "tagline": "STANDBY"},
    "overdrive": {"name": "OVERDRIVE", "primary": "#ff3a4c",   "secondary": "#ff7a3a",   "accent": "#ffd166", "glow": "#ff3a4c",   "speed": 1.7,  "tagline": "COMBAT READY"},
    "focus":     {"name": "FOCUS",     "primary": "#5fdbff",   "secondary": "#7fd6ff",   "accent": "#e8fbff", "glow": "#5fdbff",   "speed": 0.55, "tagline": "DEEP WORK"},
    "stealth":   {"name": "STEALTH",   "primary": "#3a5a7a",   "secondary": "#5a7a9a",   "accent": "#8aaac8", "glow": "#1a3a5a",   "speed": 0.4,  "tagline": "SILENT RUN"},
    "prism":     {"name": "PRISM",     "primary": "#ff6bd6",   "secondary": "#a86bff",   "accent": "#66ffd6", "glow": "#ff6bd6",   "speed": 1.25, "tagline": "CREATIVE FLOW"},
    "apex":      {"name": "APEX",      "primary": "#ffc94a",   "secondary": "#ff8a3a",   "accent": "#fff5d6", "glow": "#ffc94a",   "speed": 1.9,  "tagline": "FULL POWER"},
}
MODE_ORDER = ("standard", "overdrive", "focus", "stealth", "prism", "apex")
ISLAND_H = 46


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


# ==================== Performance: shared resource caches ====================
# QPen / QBrush / QFont are value-types in Qt — safe to share & cache.
# Recreating these per-draw-call is a major source of jank on this UI.
@functools.lru_cache(maxsize=512)
def _get_pen(color_hex: str, alpha: int, width: float = 1.0,
             style: int = 0):
    # 0 == Qt.PenStyle.SolidLine (default solid line)
    return QPen(qcol(color_hex, alpha), width, Qt.PenStyle(style))


@functools.lru_cache(maxsize=512)
def _get_brush(color_hex: str, alpha: int):
    return QBrush(qcol(color_hex, alpha))


@functools.lru_cache(maxsize=128)
def _get_font(family: str, size: int, bold: int = 0):
    return QFont(family, size,
                 QFont.Weight.Bold if bold else QFont.Weight.Normal)


# 3-bucket twinkle brushes (low / mid / high alpha) for stars & particles
def _twinkle_brush(color_hex: str, twinkle: float):
    """Return a brush from 3 alpha buckets to avoid creating QBrush per particle."""
    a = 60 + int(180 * max(0.0, min(1.0, twinkle)))
    bucket = 1 if a < 120 else (2 if a < 200 else 3)
    return _get_brush(color_hex, bucket * 60 if bucket == 1 else
                     (120 if bucket == 2 else 220))


# ==================== Particle Generators ====================
def make_sphere_particles(count: int = 220) -> list[dict]:
    particles = []
    golden_angle = math.pi * (3 - math.sqrt(5))
    for i in range(count):
        y = 1 - (i / float(count - 1)) * 2
        radius_at_y = math.sqrt(max(0.0, 1 - y * y))
        theta = golden_angle * i
        particles.append({
            "x": math.cos(theta) * radius_at_y + random.uniform(-0.04, 0.04),
            "y": y + random.uniform(-0.04, 0.04),
            "z": math.sin(theta) * radius_at_y + random.uniform(-0.04, 0.04),
            "size": random.uniform(1.0, 2.6),
            "phase": random.uniform(0, math.tau),
        })
    return particles


def make_stars(count: int = 80) -> list[dict]:
    return [{
        "x": random.uniform(0, 1), "y": random.uniform(0, 1),
        "size": random.uniform(0.3, 1.0),
        "phase": random.uniform(0, math.tau),
        "color": random.choice([C.TEXT, "#b8ecff", "#7fd6ff", "#ffe8c0"]),
    } for _ in range(count)]


def make_plasma_arcs(main_count: int = 14, branch_count: int = 18,
                    segments: int = 18) -> list[dict]:
    arcs = []
    for i in range(main_count):
        base_ang = (i / main_count) * math.tau + random.uniform(-0.12, 0.12)
        pts = []
        for s in range(segments + 1):
            t = s / segments
            bx = math.cos(base_ang) * t
            by = math.sin(base_ang) * t
            perp_x = -math.sin(base_ang)
            perp_y =  math.cos(base_ang)
            jit = (random.random() - 0.5) * 0.18 * math.sin(t * math.pi)
            r_jit = (random.random() - 0.5) * 0.08
            cur_r = math.sqrt(bx * bx + by * by) + r_jit
            if cur_r < 0.01:
                cur_r = 0.01
            bx = (bx / math.sqrt(bx * bx + by * by + 1e-9)) * cur_r
            by = (by / math.sqrt(bx * bx + by * by + 1e-9)) * cur_r
            bx += perp_x * jit
            by += perp_y * jit
            pts.append((bx, by, t))
        arcs.append({
            "kind": "main", "phase": random.uniform(0, math.tau),
            "speed": random.uniform(2.5, 5.0),
            "pts": pts,
        })
    for _ in range(branch_count):
        base_ang = random.uniform(0, math.tau)
        start_t = random.uniform(0.25, 0.7)
        length = random.uniform(0.15, 0.4)
        pts = []
        bx, by = math.cos(base_ang) * start_t, math.sin(base_ang) * start_t
        cur = (bx, by)
        steps = 7
        for s in range(steps + 1):
            t = s / steps
            pts.append((cur[0] + math.cos(base_ang) * t * length,
                        cur[1] + math.sin(base_ang) * t * length,
                        start_t + t * length))
        arcs.append({
            "kind": "branch", "phase": random.uniform(0, math.tau),
            "speed": random.uniform(4.0, 8.0),
            "pts": pts,
        })
    return arcs


def make_sparks(count: int = 60) -> list[dict]:
    sparks = []
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        r = random.uniform(0.0, 0.95)
        sparks.append({
            "x": math.cos(ang) * r,
            "y": math.sin(ang) * r,
            "life": random.uniform(0, 1),
            "max_life": random.uniform(0.6, 1.4),
            "size": random.uniform(0.6, 2.2),
            "ang": ang,
        })
    return sparks


# ── 3D helpers ────────────────────────────────────────────────────────────────
def _bilinear(quad, u, v):
    """Bilinear interpolation in a 4-point quad (p1, p2, p3, p4).
    quad[0]=bottom-left, quad[1]=bottom-right, quad[2]=top-right, quad[3]=top-left
    u goes 0->1 left-to-right, v goes 0->1 bottom-to-top.
    """
    p1, p2, p3, p4 = quad
    a = (p1[0] * (1 - u) + p2[0] * u,
         p1[1] * (1 - u) + p2[1] * u)
    b = (p4[0] * (1 - u) + p3[0] * u,
         p4[1] * (1 - u) + p3[1] * u)
    return (a[0] * (1 - v) + b[0] * v,
            a[1] * (1 - v) + b[1] * v)


def kind_in_view(*z_values, max_z=0):
    """Heuristic: face is visible if any vertex has z <= max_z (closer to camera)."""
    return any(z <= max_z for z in z_values)


# ==================== World Map Data ====================
# Simplified continent outlines in (latitude, longitude) order.
# Used by _draw_world_map (holographic tactical map).
_WORLD_CONTINENTS = [
    # North America
    [(70, -165), (74, -130), (70, -90), (62, -65),
     (50, -55), (35, -75), (25, -80), (16, -88),
     (10, -84), (16, -97), (32, -117), (45, -125),
     (58, -135), (66, -165)],
    # South America
    [(12, -72), (10, -62), (0, -50), (-10, -35),
     (-23, -42), (-35, -58), (-55, -70), (-20, -75),
     (-5, -80), (0, -80)],
    # Europe
    [(71, 25), (65, 35), (55, 40), (45, 42),
     (38, 28), (36, 15), (36, -5), (43, -10),
     (50, -5), (58, -7), (62, 5)],
    # Africa
    [(35, -8), (32, 10), (31, 32), (12, 44),
     (0, 42), (-25, 35), (-34, 20), (-15, 12),
     (0, 8), (15, -16), (25, -16)],
    # Asia
    [(78, 60), (78, 100), (73, 140), (68, 170),
     (60, 165), (50, 155), (38, 142), (20, 110),
     (8, 105), (15, 78), (30, 50), (50, 60), (60, 70)],
    # Australia
    [(-10, 135), (-15, 145), (-30, 153), (-38, 145),
     (-35, 117), (-22, 113), (-15, 125)],
    # Antarctica (simple line at the bottom)
    [(-65, -180), (-72, -120), (-78, -60), (-72, 0),
     (-70, 60), (-75, 120), (-70, 180)],
]

# Major data nodes (cities) in (lat, lon)
_WORLD_NODES = [
    (40.7, -74.0, "NYC"),
    (51.5,  -0.1, "LDN"),
    (48.9,   2.3, "PAR"),
    (52.5,  13.4, "BER"),
    (55.8,  37.6, "MOW"),
    (28.6,  77.2, "DEL"),
    (35.7, 139.7, "TKY"),
    (31.2, 121.5, "SHA"),
    (1.3,  103.8, "SGP"),
    (30.0,  31.2, "CAI"),
    (-23.6, -46.6, "SAO"),
    (-33.9, 151.2, "SYD"),
    (34.0, -118.2, "LAX"),
    (19.4,  -99.1, "MEX"),
    (60.2,  24.9, "HEL"),
    (-34.6,  18.4, "CPT"),
    (25.2,  55.3, "DXB"),
    (39.9,  116.4, "BJS"),
]

# Animated data-flow links between major cities (lat, lon pairs)
_WORLD_LINKS = [
    ((40.7, -74.0), (51.5, -0.1)),
    ((35.7, 139.7), (-33.9, 151.2)),
    ((48.9, 2.3), (28.6, 77.2)),
    ((40.7, -74.0), (34.0, -118.2)),
    ((55.8, 37.6), (39.9, 116.4)),
    ((1.3, 103.8), (25.2, 55.3)),
    ((-23.6, -46.6), (-34.6, 18.4)),
    ((30.0, 31.2), (52.5, 13.4)),
    ((19.4, -99.1), (40.7, -74.0)),
    ((51.5, -0.1), (60.2, 24.9)),
]

# ==================== 3D Laptop static data ====================
# Local-space vertex slots (computed per-frame, but face index lists are static).
# Base box indices: 0-7, Screen box indices: 8-15 (per _draw_3d_laptop).
_LAPTOP_FACES = [
    # (indices, fill, edge, alpha, kind)
    ([4, 5, 6, 7],     C.PANEL_HI,   "#5a7a98", 235, "base_top"),
    ([0, 3, 2, 1],     C.PANEL_DARK, "#1a2a40", 220, "base_bot"),
    ([0, 1, 5, 4],     C.PANEL,      "#3a5a7a", 230, "base_front"),
    ([3, 7, 6, 2],     C.PANEL_HI,   "#3a5a7a", 220, "base_back"),
    ([0, 4, 7, 3],     C.PANEL,      "#2a4a6a", 225, "base_left"),
    ([1, 2, 6, 5],     C.PANEL,      "#2a4a6a", 225, "base_right"),
    ([8, 9, 10, 11],   "#02060a",    "#3a5a7a", 250, "screen_front"),
    ([12, 15, 14, 13], C.PANEL_DARK, "#1a2a40", 220, "screen_back"),
    ([8, 11, 15, 12],  C.PANEL,      "#2a4a6a", 225, "screen_left"),
    ([9, 13, 14, 10],  C.PANEL,      "#2a4a6a", 225, "screen_right"),
    ([10, 11, 15, 14], C.PANEL_HI,   "#3a5a7a", 220, "screen_top"),
]

# Pre-compute keyboard key grid (12 × 5) — list of (u0, v0, u1, v1, is_space)
_LAPTOP_KEYS: list = []
for _ix in range(12):
    for _iz in range(5):
        _u0 = 0.06 + _ix * (1 - 0.12) / 12
        _u1 = _u0 + (1 - 0.12) / 12 * 0.85
        _v0 = 0.18 + _iz * (1 - 0.36) / 5
        _v1 = _v0 + (1 - 0.36) / 5 * 0.75
        _is_space = (_ix == 5 or _ix == 6) and _iz == 4
        _LAPTOP_KEYS.append((_u0, _v0, _u1, _v1, _is_space))

# Pre-compute laptop local vertices (scale=1.0, back_tilt=15° — both constant)
# 16 vertices: indices 0-7 = base, 8-15 = screen (per _draw_3d_laptop)
_LW, _LD, _LHb, _LHs, _LTk = 200.0, 140.0, 7.0, 125.0, 5.0
_Ldy = _LHs * math.cos(math.radians(15))
_Ldz = _LHs * math.sin(math.radians(15))
_LAPTOP_VERTS: list = [
    (-_LW/2, -_LHb/2, -_LD/2),  # 0  front-left-bot
    ( _LW/2, -_LHb/2, -_LD/2),  # 1  front-right-bot
    ( _LW/2, -_LHb/2,  _LD/2),  # 2  back-right-bot
    (-_LW/2, -_LHb/2,  _LD/2),  # 3  back-left-bot
    (-_LW/2,  _LHb/2, -_LD/2),  # 4  front-left-top
    ( _LW/2,  _LHb/2, -_LD/2),  # 5  front-right-top
    ( _LW/2,  _LHb/2,  _LD/2),  # 6  back-right-top
    (-_LW/2,  _LHb/2,  _LD/2),  # 7  back-left-top
    (-_LW/2,  _LHb/2,         _LD/2),            # 8  hinge-left-front
    ( _LW/2,  _LHb/2,         _LD/2),            # 9  hinge-right-front
    ( _LW/2,  _LHb/2 + _Ldy,  _LD/2 + _Ldz),    # 10 top-right-front
    (-_LW/2,  _LHb/2 + _Ldy,  _LD/2 + _Ldz),    # 11 top-left-front
    (-_LW/2,  _LHb/2,         _LD/2 + _LTk),    # 12 hinge-left-back
    ( _LW/2,  _LHb/2,         _LD/2 + _LTk),    # 13 hinge-right-back
    ( _LW/2,  _LHb/2 + _Ldy,  _LD/2 + _Ldz + _LTk),  # 14 top-right-back
    (-_LW/2,  _LHb/2 + _Ldy,  _LD/2 + _Ldz + _LTk),  # 15 top-left-back
]

# Threat zone coordinates (lat, lon, radius-deg, severity 1-3)
_WORLD_THREATS = [
    (34.5, 69.2,  4.0, 3),   # Central Asia
    (15.5, 44.2,  3.0, 2),   # Yemen
    (50.5, 30.5,  3.5, 2),   # Ukraine
    (-5.0, 18.0,  3.0, 1),   # Central Africa
    (12.0, -86.0, 2.5, 1),   # Nicaragua
]


# ==================== SciFiHud Widget ====================
class SciFiHud(QWidget):
    action_triggered = pyqtSignal(str)


    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Geometry cache (cleared on resize)
        self._panel_cache:  dict = {}
        self._corner_cache: dict = {}

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick         = 0
        self._time_phase   = 0.0
        self._scan_y       = 0.0

        self._sphere_particles = make_sphere_particles(120)
        self._sphere_angle_y   = 0.0
        self._sphere_angle_x   = 0.35

        self._stars = make_stars(60)

        self._plasma_arcs = make_plasma_arcs(10, 12, 12)
        self._sparks     = make_sparks(35)
        self._sparks_alive = 0

        self._log: list[dict] = []
        self._max_log = 30

        self._tools_used     = 0
        self._current_tool: str | None = None

        self._r_color     = (C.ACCENT, C.ACCENT_BR, "#e8fbff", C.SUCCESS)
        self._r_intensity = 1.0
        self._r_speed     = 1.0
        self.set_reactor_state("INITIALISING")

        self._active_tab = 0
        self._tab_rects: list[QRectF] = []
        self._tab_codes = ["intelligence", "notes", "tasks"]

        self._tabs = ["Intelligence", "Notes", "Tasks"]

        self._btn_rects:   list[tuple[QRectF, str]] = []
        self._card_rects:  list[tuple[QRectF, str]] = []
        self._mini_tabs:   list[tuple[QRectF, str]] = []
        self._action_rects: list[tuple[QRectF, str]] = []
        self._toggle_rect: QRectF = QRectF()
        self._send_rect:   QRectF = QRectF()
        self._term_rect:   QRectF = QRectF()
        self._cube_rect:   QRectF = QRectF()
        self._reactor_rect: QRectF = QRectF()

        self._active_right_tab = "CHAT"
        self._deep_search = True
        self._dragging_sphere = False
        self._last_mouse = QPointF()
        self._pulse_accents: list[QRectF] = []
        self._pulse_until   = 0.0

        self._cpu_pct = 12.0
        self._mem_pct = 38.0
        self._network_ms = 42.0
        self._boot_time = datetime.now()
        self._wave_phase = 0.0
        self._wave_samples = [0.0] * 64
        self._system_log: list[str] = []

        # ── NEURAL CORE data ──
        self._tool_stats: dict[str, int] = {}
        self._event_log: list[dict] = []
        self._event_log_max = 24
        self._spectrum: list[float] = [0.0] * 40
        self._spectrum_phase: list[float] = [random.uniform(0, math.tau) for _ in range(40)]
        self._cpu_history: list[float] = []
        self._mem_history: list[float] = []
        self._net_history: list[float] = []
        self._hist_max = 60
        self._core_panel_rect: QRectF = QRectF()

        # ── World map geometry cache (rebuilt only on resize) ──
        self._wmap_cache_key: tuple = ()
        self._wmap_continents: list = []   # [(centroid_x, centroid_y, poly, pts)]
        self._wmap_continent_bbox_r: list = []
        self._wmap_nodes: list = []        # [(x, y, label)]
        self._wmap_links: list = []        # [(x1, y1, x2, y2, path)]
        self._wmap_threats: list = []      # [(x, y, r, sev)]
        self._wmap_stars: list = []        # [(x, y, size)]
        self._wmap_grid_lines: list = []   # list of (x1,y1,x2,y2)
        self._wmap_eq_y: float = 0.0
        self._wmap_greenwich_x: float = 0.0
        try:
            import psutil as _ps
            self._psutil = _ps
            self._cpu_pct = float(_ps.cpu_percent(interval=None))
            self._mem_pct = float(_ps.virtual_memory().percent)
        except Exception:
            self._psutil = None

        self._audio_level      = 0.0
        self._audio_target     = 0.0
        self._reactor_pulse    = 0.0
        self._reactor_emit_t   = 0.0
        self._input_rect: QRectF = QRectF()
        self._ready_chat = False

        # ── Operational Mode + Dynamic Island state ──
        self._mode               = "standard"
        self._mode_anim_t        = 0.0
        self._mode_anim_enter    = True
        self._island_rect        = QRectF()
        self._island_close_rect  = QRectF()
        self._last_mode_change_t = -10.0

        # ── Pinned Cards (Dynamic Island content) ──
        self._pinned_cards:     list[dict] = []   # [{id, type, title, data, pinned_at, anim_state, anim_t, h}, ...]
        self._next_card_id      = 0
        self._panel_expanded    = True
        self._panel_collapse_rect: QRectF = QRectF()
        self._card_close_rects: list[tuple[str, QRectF]] = []  # (card_id, rect)
        self._card_action_rects: list[tuple[str, str, QRectF]] = []  # (card_id, action, rect)
        self._card_scroll       = 0
        self._card_max_visible  = 3

        # ── Reasoning Trace + Memory Recall display state ──
        self._trace_events:    list[dict] = []   # [{kind, msg, t}, ...]
        self._recalls:         list[dict] = []   # [{query, fact, t}, ...]
        self._show_trace:      bool = True
        self._trace_collapsed: bool = False

        # ── Voice Waveform Visualizer state (lower half of center column) ──
        self._wave_bars: list[float]    = [0.0] * 48      # 48 spectrum bars (0..1)
        self._wave_phase: float         = 0.0              # 0..2π oscilloscope phase
        self._wave_level: float         = 0.0              # smooth overall level
        self._wave_peak_hold: list[float] = [0.0] * 48    # peak-hold markers
        self._wave_source: str          = "idle"           # idle | user | aegis
        self._wave_rect: QRectF         = QRectF()
        self._wave_label_rect: QRectF   = QRectF()
        self._agent_status: dict[str, str] = {}
        self._cards_scrollbar_rect: QRectF = QRectF()
        self._cards_scrollbar_thumb: QRectF = QRectF()
        self._dragging_scrollbar = False
        self._scrollbar_drag_offset = 0.0

        # ── Card auto-remove timer (seconds) ──
        self._card_ttl = 5.0

        self._line_edit = QLineEdit(self)
        self._line_edit.setPlaceholderText("Ask Aegis anything...")
        self._line_edit.setFont(QFont("Courier New", 10))
        self._line_edit.setStyleSheet(
            "QLineEdit { background: transparent; color: " + C.TEXT + ";"
            " border: none; padding: 4px 8px; selection-background-color: " + C.ACCENT + ";"
            " selection-color: #000; }"
        )
        self._line_edit.returnPressed.connect(self._on_chat_enter)
        self._line_edit.hide()

        # ── Notes & Tasks storage (in-memory mirror of JSON) ──
        self._notes: list[dict] = self._load_notes()
        self._tasks: list[dict] = self._load_tasks()
        self._task_priority: str = "medium"
        self._notes_scroll: int = 0
        self._tasks_scroll: int = 0

        self._note_input_rect:  QRectF = QRectF()
        self._task_input_rect:  QRectF = QRectF()
        self._task_prio_rects:  list[tuple[QRectF, str]] = []
        self._note_del_rects:   list[tuple[QRectF, int]] = []
        self._task_check_rects: list[tuple[QRectF, int]] = []
        self._task_del_rects:   list[tuple[QRectF, int]] = []
        self._task_clear_rect:  QRectF = QRectF()

        # ── Note input ──
        self._note_edit = QLineEdit(self)
        self._note_edit.setPlaceholderText("New note...")
        self._note_edit.setFont(QFont("Courier New", 10))
        self._note_edit.setStyleSheet(
            "QLineEdit { background: transparent; color: " + C.TEXT + ";"
            " border: none; padding: 4px 8px; selection-background-color: " + C.AMBER + ";"
            " selection-color: #000; }"
        )
        self._note_edit.returnPressed.connect(self._on_note_enter)
        self._note_edit.hide()

        # ── Task input ──
        self._task_edit = QLineEdit(self)
        self._task_edit.setPlaceholderText("New task...")
        self._task_edit.setFont(QFont("Courier New", 10))
        self._task_edit.setStyleSheet(
            "QLineEdit { background: transparent; color: " + C.TEXT + ";"
            " border: none; padding: 4px 8px; selection-background-color: " + C.ROSE + ";"
            " selection-color: #000; }"
        )
        self._task_edit.returnPressed.connect(self._on_task_enter)
        self._task_edit.hide()

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(33)

    # ==================== Public API ====================
    def set_reactor_state(self, state: str):
        palette = STATE_PALETTES.get(state, STATE_PALETTES["LISTENING"])
        intensity = {"INITIALISING": 0.75, "LISTENING": 1.0, "SPEAKING": 1.4,
                     "THINKING": 1.0, "MUTED": 0.4}
        speed = {"INITIALISING": 0.5, "LISTENING": 1.0, "SPEAKING": 1.7,
                 "THINKING": 1.2, "MUTED": 0.25}
        self._r_color     = palette
        self._r_intensity = intensity.get(state, 1.0)
        self._r_speed     = speed.get(state, 1.0)
        # Map reactor state → waveform source
        if state == "SPEAKING":
            self._wave_source = "aegis"
        elif state == "LISTENING":
            self._wave_source = "user"
        elif state == "MUTED":
            self._wave_source = "idle"

    def set_audio_level(self, level: float):
        try:
            self._audio_target = max(0.0, min(1.0, float(level)))
        except Exception:
            self._audio_target = 0.0

    # ── Mode + Dynamic Island ─────────────────────────────────────────
    def set_mode(self, name: str) -> bool:
        """Switch to a named operational mode. Returns True if it changed."""
        key = (name or "").lower().strip()
        if key not in MODES:
            return False
        if key == self._mode:
            return False
        self._mode           = key
        self._mode_anim_t    = 0.0
        self._mode_anim_enter = True
        self._last_mode_change_t = self._time_phase
        self._emit_action("mode", MODES[key]["name"])
        return True

    def cycle_mode(self) -> str:
        """Advance to the next mode in MODE_ORDER. Returns the new mode key."""
        try:
            i = MODE_ORDER.index(self._mode)
        except ValueError:
            i = 0
        nxt = MODE_ORDER[(i + 1) % len(MODE_ORDER)]
        self.set_mode(nxt)
        return nxt

    def current_mode(self) -> str:
        return self._mode

    # ── Pinned Cards API ─────────────────────────────────────────────
    def pin_card(self, type_: str, title: str, data: dict, ttl: float = 0.0) -> str:
        """Pin a new card. Returns card id. Duplicates (same type+title) are
        replaced rather than stacked, so live updates work naturally.
        ttl: auto-remove after N seconds; 0 = use self._card_ttl (default 5s);
        pass a negative value to disable auto-remove for this card."""
        now = time.time()
        if ttl == 0.0:
            ttl = self._card_ttl
        if ttl > 0:
            auto_remove_at = now + ttl
        else:
            auto_remove_at = 0.0  # disabled
        # Replace existing card of same type+title (e.g. weather refresh)
        for c in self._pinned_cards:
            if c["type"] == type_ and c["title"] == title and c["anim_state"] != "leaving":
                c["data"]           = dict(data)
                c["pinned_at"]      = now
                c["anim_t"]         = 0.0
                c["anim_state"]     = "pulse"
                c["auto_remove_at"] = auto_remove_at
                return c["id"]
        self._next_card_id += 1
        card = {
            "id":             f"c{self._next_card_id}",
            "type":           type_,
            "title":          title,
            "data":           dict(data or {}),
            "pinned_at":      now,
            "anim_state":     "entering",
            "anim_t":         0.0,
            "h":              0.0,
            "auto_remove_at": auto_remove_at,
        }
        self._pinned_cards.append(card)
        # Auto-scroll to newest
        self._card_scroll = max(0, len(self._pinned_cards) - self._card_max_visible)
        return card["id"]

    def unpin_card(self, card_id: str) -> bool:
        """Animate a card out. Returns True if found."""
        for c in self._pinned_cards:
            if c["id"] == card_id and c["anim_state"] != "leaving":
                c["anim_state"] = "leaving"
                c["anim_t"]     = 0.0
                return True
        return False

    def clear_cards(self) -> int:
        """Animate all cards out. Returns count."""
        n = 0
        for c in self._pinned_cards:
            if c["anim_state"] != "leaving":
                c["anim_state"] = "leaving"
                c["anim_t"]     = 0.0
                n += 1
        return n

    def list_cards(self) -> list[dict]:
        """Snapshot of currently pinned (non-leaving) cards."""
        return [
            {"id": c["id"], "type": c["type"], "title": c["title"], "data": c["data"]}
            for c in self._pinned_cards
            if c["anim_state"] != "leaving"
        ]

    def has_pinned_card(self, type_: str) -> bool:
        for c in self._pinned_cards:
            if c["type"] == type_ and c["anim_state"] != "leaving":
                return True
        return False

    def _gc_cards(self):
        """Drop fully-animated-out cards."""
        self._pinned_cards = [
            c for c in self._pinned_cards
            if not (c["anim_state"] == "leaving" and c["anim_t"] >= 1.0)
        ]
        # Clamp scroll
        max_scroll = max(0, len(self._pinned_cards) - self._card_max_visible)
        if self._card_scroll > max_scroll:
            self._card_scroll = max_scroll

    def _toggle_panel(self):
        if self._mode == "standard":
            return
        self._panel_expanded = not self._panel_expanded

    def set_card_ttl(self, seconds: float):
        """Set how long cards stay pinned before auto-removing (in seconds)."""
        try:
            self._card_ttl = max(1.0, float(seconds))
        except Exception:
            pass

    # ── Reasoning Trace API ──
    def add_trace(self, kind: str, msg: str) -> None:
        """Push a trace event for the chat panel to display.
        kind: 'thought' | 'tool' | 'result' | 'plan' | 'error'"""
        from datetime import datetime as _dt
        self._trace_events.append({
            "kind": kind, "msg": str(msg)[:200], "t": _dt.now()
        })
        if len(self._trace_events) > 50:
            self._trace_events = self._trace_events[-50:]

    def clear_trace(self) -> None:
        self._trace_events.clear()

    def set_show_trace(self, show: bool) -> None:
        self._show_trace = bool(show)

    def toggle_trace_collapsed(self) -> None:
        self._trace_collapsed = not self._trace_collapsed

    # ── Proactive Memory Recall API ──
    def add_recall(self, query: str, fact: str) -> None:
        """Show an inline 'I remember...' chip in the chat panel."""
        from datetime import datetime as _dt
        self._recalls.append({
            "query": str(query)[:80],
            "fact": str(fact)[:200],
            "t": _dt.now()
        })
        if len(self._recalls) > 8:
            self._recalls = self._recalls[-8:]

    def clear_recalls(self) -> None:
        self._recalls.clear()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Invalidate geometry caches — panel/corner paths and world map
        # are tied to widget dimensions.
        self._panel_cache.clear()
        self._corner_cache.clear()
        self._wmap_cache_key = ()

    def _on_chat_enter(self):
        text = self._line_edit.text().strip()
        if not text:
            return
        self._line_edit.clear()
        self._emit_action("send", text)

    # ─────────────────────── Notes / Tasks storage ───────────────────────
    def _notes_file(self) -> Path:
        d = BASE_DIR / "memory" / "notes"
        d.mkdir(parents=True, exist_ok=True)
        return d / "notes.json"

    def _tasks_file(self) -> Path:
        d = BASE_DIR / "memory" / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        return d / "tasks.json"

    def _load_notes(self) -> list[dict]:
        try:
            f = self._notes_file()
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_notes_to_disk(self) -> None:
        try:
            self._notes_file().write_text(
                json.dumps(self._notes, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_tasks(self) -> list[dict]:
        try:
            f = self._tasks_file()
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_tasks_to_disk(self) -> None:
        try:
            self._tasks_file().write_text(
                json.dumps(self._tasks, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _add_note(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        cat = self._detect_note_category(text)
        nid = max([n.get("id", 0) for n in self._notes], default=0) + 1
        self._notes.insert(0, {
            "id":        nid,
            "title":     text[:48].strip() or "Quick Note",
            "body":      text,
            "category":  cat,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        self._save_notes_to_disk()
        self._notes_scroll = 0
        self.add_log("SYS: Note saved - " + text[:40])

    def _delete_note(self, note_id: int) -> None:
        before = len(self._notes)
        self._notes = [n for n in self._notes if n.get("id") != note_id]
        if len(self._notes) != before:
            self._save_notes_to_disk()
            self.add_log("SYS: Note #" + str(note_id) + " deleted")

    def _detect_note_category(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["study", "padh", "exam", "learn", "course"]):
            return "study"
        if any(w in t for w in ["idea", "soch", "plan", "concept", "insight"]):
            return "idea"
        if any(w in t for w in ["karna", "todo", "task", "remind", "must"]):
            return "todo"
        if any(w in t for w in ["work", "meeting", "client", "project", "deadline"]):
            return "work"
        if any(w in t for w in ["personal", "private", "diary", "feel", "mood"]):
            return "personal"
        return "general"

    def _add_task(self, text: str, priority: str | None = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        pr = priority or self._task_priority
        if pr not in ("high", "medium", "low"):
            pr = self._detect_task_priority(text)
        tid = max([t.get("id", 0) for t in self._tasks], default=0) + 1
        self._tasks.insert(0, {
            "id":         tid,
            "text":       text,
            "done":       False,
            "priority":   pr,
            "due":        None,
            "created":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            "completed":  None,
        })
        self._save_tasks_to_disk()
        self._tasks_scroll = 0
        self.add_log("SYS: Task added - " + text[:40] + " [" + pr.upper() + "]")

    def _toggle_task(self, task_id: int) -> None:
        for t in self._tasks:
            if t.get("id") == task_id:
                t["done"] = not t.get("done", False)
                t["completed"] = datetime.now().strftime("%Y-%m-%d %H:%M") if t["done"] else None
                self._save_tasks_to_disk()
                self.add_log(
                    "SYS: Task #" + str(task_id) + (" done" if t["done"] else " re-opened")
                )
                return

    def _delete_task(self, task_id: int) -> None:
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.get("id") != task_id]
        if len(self._tasks) != before:
            self._save_tasks_to_disk()
            self.add_log("SYS: Task #" + str(task_id) + " removed")

    def _clear_done_tasks(self) -> None:
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if not t.get("done")]
        n = before - len(self._tasks)
        if n:
            self._save_tasks_to_disk()
            self.add_log("SYS: Cleared " + str(n) + " completed task(s)")

    def _detect_task_priority(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["urgent", "asap", "jaldi", "turant", "important", "zaroor"]):
            return "high"
        if any(w in t for w in ["baad", "later", "kal", "tomorrow", "someday", "jab time"]):
            return "low"
        return "medium"

    def _on_note_enter(self) -> None:
        text = self._note_edit.text().strip()
        if not text:
            return
        self._note_edit.clear()
        self._add_note(text)

    def _on_task_enter(self) -> None:
        text = self._task_edit.text().strip()
        if not text:
            return
        self._task_edit.clear()
        self._add_task(text)

    def add_log(self, text: str):
        kind = "info"
        up = text.upper()
        if up.startswith("ERR"):       kind = "error"
        elif up.startswith("YOU:"):    kind = "user"
        elif up.startswith("AEGIS"):  kind = "assistant"
        elif up.startswith("SYS"):     kind = "system"
        self._log.append({"text": text, "kind": kind, "time": datetime.now()})
        if len(self._log) > self._max_log:
            self._log.pop(0)

    def notify_tool(self, name=None):
        if name:
            self._current_tool = name
            self._tool_stats[name] = self._tool_stats.get(name, 0) + 1
            self._add_event("tool", name + " armed")
        else:
            self._tools_used += 1
            self._current_tool = None
            self._add_event("ok", "tool cycle complete")

    def _add_event(self, kind: str, text: str):
        self._event_log.append({"kind": kind, "text": text, "time": datetime.now()})
        if len(self._event_log) > self._event_log_max:
            self._event_log.pop(0)

    def mousePressEvent(self, e):
        pos = e.position()
        # 1. Close-mode × on pill
        if self._mode != "standard" and not self._island_close_rect.isEmpty() \
                and self._island_close_rect.contains(pos):
            self.set_mode("standard")
            return
        # 2. Pill collapse/expand arrow
        if self._mode != "standard" and not self._panel_collapse_rect.isEmpty() \
                and self._panel_collapse_rect.contains(pos):
            self._toggle_panel()
            return
        # 3. Card × close buttons
        if self._mode != "standard":
            for cid, rect in self._card_close_rects:
                if rect.contains(pos):
                    self.unpin_card(cid)
                    return
        if self._line_edit.isVisible() and self._input_rect.contains(pos):
            self._line_edit.setFocus()
            return
        if self._note_edit.isVisible() and self._note_input_rect.contains(pos):
            self._note_edit.setFocus()
            return
        if self._task_edit.isVisible() and self._task_input_rect.contains(pos):
            self._task_edit.setFocus()
            return
        for i, rect in enumerate(self._tab_rects):
            if rect.contains(pos):
                self._active_tab = i
                self._pulse(rect)
                self._emit_action("tab", self._tab_codes[i])
                self._line_edit.setVisible(i == 0)
                self._note_edit.setVisible(i == 1)
                self._task_edit.setVisible(i == 2)
                return
        for rect, code in self._btn_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._emit_action("button", code)
                return
        for rect, code in self._card_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._emit_action("card", code)
                return
        for rect, code in self._mini_tabs:
            if rect.contains(pos):
                if code != self._active_right_tab:
                    self._active_right_tab = code
                    self._pulse(rect)
                    self._emit_action("minitab", code)
                return
        if self._toggle_rect.contains(pos):
            self._deep_search = not self._deep_search
            self._pulse(self._toggle_rect)
            self._emit_action("toggle", "1" if self._deep_search else "0")
            return
        # Trace header click → toggle collapse
        if not self._trace_toggle_rect.isEmpty() and self._trace_toggle_rect.contains(pos):
            self.toggle_trace_collapsed()
            return
        if self._send_rect.contains(pos):
            self._pulse(self._send_rect)
            text = self._line_edit.text().strip() if self._line_edit.isVisible() else ""
            if text:
                self._line_edit.clear()
            self._emit_action("send", text)
            return
        if hasattr(self, "_note_send_rect") and self._note_send_rect.contains(pos):
            self._pulse(self._note_send_rect)
            text = self._note_edit.text().strip() if self._note_edit.isVisible() else ""
            if text:
                self._note_edit.clear()
                self._add_note(text)
            return
        if hasattr(self, "_task_send_rect") and self._task_send_rect.contains(pos):
            self._pulse(self._task_send_rect)
            text = self._task_edit.text().strip() if self._task_edit.isVisible() else ""
            if text:
                self._task_edit.clear()
                self._add_task(text)
            return
        for rect, nid in self._note_del_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._delete_note(nid)
                return
        for rect, tid in self._task_check_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._toggle_task(tid)
                return
        for rect, tid in self._task_del_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._delete_task(tid)
                return
        for rect, pr in self._task_prio_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._task_priority = pr
                return
        if not self._task_clear_rect.isEmpty() and self._task_clear_rect.contains(pos):
            self._pulse(self._task_clear_rect)
            self._clear_done_tasks()
            return
        if self._term_rect.contains(pos):
            self._pulse(self._term_rect)
            self._emit_action("terminate", "")
            return
        if self._cube_rect.contains(pos):
            self._pulse(self._cube_rect)
            self._emit_action("hub", "visual")
            return
        if self._reactor_rect.contains(pos):
            self._pulse(self._reactor_rect)
            self._emit_action("hub", "reactor")
            return
        for rect, code in self._action_rects:
            if rect.contains(pos):
                self._pulse(rect)
                self._emit_action("cmd", code)
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging_sphere:
            dx = e.position().x() - self._last_mouse.x()
            dy = e.position().y() - self._last_mouse.y()
            self._sphere_angle_y += dx * 0.005
            self._sphere_angle_x += dy * 0.005
            self._sphere_angle_x = max(-1.2, min(1.2, self._sphere_angle_x))
            self._last_mouse = e.position()
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._dragging_sphere = False
        super().mouseReleaseEvent(e)

    def _pulse(self, rect: QRectF):
        self._pulse_accents.append(QRectF(rect))
        self._pulse_until = time.time() + 0.35

    def _emit_action(self, kind: str, value: str):
        code = kind + ":" + value if value else kind
        self._system_log.append("[" + datetime.now().strftime("%H:%M:%S") + "] -> " + code)
        if len(self._system_log) > 20:
            self._system_log.pop(0)
        if kind in ("tab", "card", "button", "cmd", "minitab", "hub"):
            tag = "ui" if kind in ("tab", "card", "button", "minitab") else "cmd"
            txt = (kind + " " + value) if value else kind
            self._add_event(tag, txt)
        self.action_triggered.emit(code)

    # ==================== Animation step ====================
    def _step(self):
        self._tick       += 1
        self._time_phase += 0.04
        self._scan_y     += 1.2
        if self._scan_y > self.height() + 40:
            self._scan_y = -40

        sp = self._r_speed
        self._sphere_angle_y = (self._sphere_angle_y + 0.012 * sp) % math.tau
        self._sphere_angle_x = 0.35 + 0.08 * math.sin(self._time_phase * 0.5)

        for s in self._stars:
            s["phase"] += 0.05

        self._wave_phase += 0.25

        if self.state == "SPEAKING" and self._audio_target < 0.05:
            pulse = 0.5 + 0.5 * math.sin(self._time_phase * 14.0)
            secondary = 0.3 * (0.5 + 0.5 * math.sin(self._time_phase * 27.0 + 1.2))
            self._audio_target = min(1.0, 0.45 + 0.45 * pulse + secondary * 0.4)
        elif self.state == "LISTENING" and self._audio_target < 0.05:
            self._audio_target = 0.10 + 0.05 * math.sin(self._time_phase * 2.0)
        elif self.state not in ("SPEAKING", "LISTENING"):
            self._audio_target = 0.0

        diff = self._audio_target - self._audio_level
        if abs(diff) > 0.01:
            self._audio_level += diff * 0.18
        else:
            self._audio_level = self._audio_target
        self._reactor_pulse = 0.7 + 0.3 * self._audio_level

        # ── Voice Waveform bars: shift left + inject new value from source ──
        if self._wave_source == "user":
            base = 0.20 + 0.18 * math.sin(self._time_phase * 3.1)
            jitter = 0.30 * (0.5 + 0.5 * math.sin(self._time_phase * 9.0 + 0.5))
            new = max(0.0, min(1.0, base + jitter * (0.5 + 0.5 * math.sin(self._time_phase * 5.7))))
        elif self._wave_source == "aegis":
            t = self._time_phase
            new = 0.45 + 0.35 * math.sin(t * 2.3) + 0.10 * math.sin(t * 7.1 + 0.8)
            new = max(0.0, min(1.0, new))
        else:
            new = 0.06 + 0.04 * math.sin(self._time_phase * 1.3)
        # shift left by 1, append new at the right
        for i in range(len(self._wave_bars) - 1):
            self._wave_bars[i] = self._wave_bars[i + 1] * 0.92
        self._wave_bars[-1] = new
        # peak hold: slow decay
        for i in range(len(self._wave_peak_hold)):
            self._wave_peak_hold[i] = max(self._wave_peak_hold[i] * 0.96,
                                           self._wave_bars[i])
        # smooth level
        self._wave_level += (self._audio_level - self._wave_level) * 0.25
        alive = 0
        emit_rate = 0.04 + self._audio_level * 0.4
        for sp in self._sparks:
            sp["life"] -= 0.018
            if sp["life"] <= 0:
                if random.random() < emit_rate:
                    sp["ang"] = random.uniform(0, math.tau)
                    r0 = random.uniform(0.0, 0.25)
                    sp["x"] = math.cos(sp["ang"]) * r0
                    sp["y"] = math.sin(sp["ang"]) * r0
                    sp["max_life"] = random.uniform(0.5, 1.3)
                    sp["life"] = sp["max_life"]
                    sp["size"] = random.uniform(0.6, 2.2)
                else:
                    sp["life"] = 0
                    continue
            else:
                drift = 0.012 + self._audio_level * 0.04
                sp["x"] += math.cos(sp["ang"]) * drift
                sp["y"] += math.sin(sp["ang"]) * drift
                alive += 1
        self._sparks_alive = alive

        # ── Neural core data updates ──
        # Spectrum: each bar drifts via sine, modulated by audio level
        for i in range(len(self._spectrum)):
            self._spectrum_phase[i] += 0.18 + 0.06 * math.sin(self._time_phase + i * 0.3)
            base = 0.25 + 0.25 * math.sin(self._spectrum_phase[i])
            harmonic = 0.15 * math.sin(self._time_phase * 2.3 + i * 0.5)
            drift = (random.random() - 0.5) * 0.12
            env = 0.6 + 0.7 * self._audio_level
            center_boost = 1.0 - abs(i - 20) / 28.0
            center_boost = max(0.35, center_boost)
            target = max(0.0, min(1.0, (base + harmonic + drift) * env * center_boost + 0.05))
            self._spectrum[i] += (target - self._spectrum[i]) * 0.35

        # Vitals: try psutil for real values, fall back to random walk
        if self._psutil is not None:
            try:
                self._cpu_pct = float(self._psutil.cpu_percent(interval=None))
                self._mem_pct = float(self._psutil.virtual_memory().percent)
            except Exception:
                pass
        else:
            self._cpu_pct = max(2.0, min(98.0, self._cpu_pct + random.uniform(-3, 3)))
            self._mem_pct = max(15.0, min(92.0, self._mem_pct + random.uniform(-1.5, 1.5)))
        self._network_ms = max(4.0, min(220.0,
            self._network_ms + random.uniform(-6, 6) + (5 if random.random() < 0.04 else 0)))
        self._cpu_history.append(self._cpu_pct)
        self._mem_history.append(self._mem_pct)
        self._net_history.append(self._network_ms)
        if len(self._cpu_history) > self._hist_max:
            self._cpu_history.pop(0)
            self._mem_history.pop(0)
            self._net_history.pop(0)

        self.update()


    # ==================== Painting ====================
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W, H = self.width(), self.height()

        TOP_H    = 56
        LEFT_W   = 280
        RIGHT_W  = 330
        BOT_H    = 86
        center_x = LEFT_W
        center_w = W - LEFT_W - RIGHT_W
        center_y = TOP_H
        center_h = H - TOP_H - BOT_H
        center_top_h = 300

        # advance mode animation (0..1 over ~500ms)
        if self._mode != "standard":
            self._mode_anim_t = min(1.0, self._mode_anim_t + 0.05)
            self._gc_cards()
            self._update_card_anims()

        try:
            # Background + stars ALWAYS render (so dynamic panel has the starfield)
            self._draw_background(p, W, H)
            self._draw_stars(p, W, H)

            # Standard full HUD layout
            self._draw_top_bar(p, 0, 0, W, TOP_H)
            self._draw_left_column(p, 0, TOP_H, LEFT_W, center_h)
            self._draw_right_column(p, W - RIGHT_W, TOP_H, RIGHT_W, center_h)

            # Centre column — REPLACE with dynamic panel when mode is active
            if self._mode != "standard":
                self._draw_dynamic_panel(p, center_x, center_y, center_w, H - center_y - BOT_H)
            else:
                self._draw_center_top(p, center_x, center_y, center_w, H - center_y - BOT_H)

                bot_y = H - BOT_H
                self._draw_terminal_log(p, W - RIGHT_W - 320, bot_y + 8, 300, BOT_H - 16)

                self._draw_pulses(p)

            if self._mode != "standard":
                self._draw_island_scan(p)
            self._draw_scan_line(p, W, H)
            self._draw_vignette(p, W, H)
        except Exception as e:
            # Safety net: if any drawing crashes, render a minimal visible
            # fallback so the UI never goes completely black.
            try:
                p.fillRect(self.rect(), QBrush(QColor("#0a0f1c")))
                p.setPen(QPen(QColor("#ff3a4c"), 1))
                p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
                p.drawText(QRectF(20, 20, W - 40, 200),
                           Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                           "PAINT ERROR (HUD recovered):\n" + repr(e)[:300])
            except Exception:
                pass

    # ----- Background -----
    def _draw_background(self, p, W, H):
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0.0, qcol("#080c16"))
        grad.setColorAt(0.5, qcol("#0a0f1c"))
        grad.setColorAt(1.0, qcol("#060a12"))
        p.fillRect(self.rect(), QBrush(grad))
        glow = QRadialGradient(QPointF(W / 2, H / 2), max(W, H) * 0.55)
        glow.setColorAt(0.0, qcol("#0a1a30", 50))
        glow.setColorAt(0.6, qcol("#0a1424", 25))
        glow.setColorAt(1.0, qcol("#000000", 0))
        p.fillRect(self.rect(), QBrush(glow))

    def _draw_stars(self, p, W, H):
        # OPTIMIZED: 3 alpha-bucket brushes per star color (low/mid/high twinkle)
        p.setPen(Qt.PenStyle.NoPen)
        brushes = {}
        for s in self._stars:
            c = s["color"]
            if c not in brushes:
                brushes[c] = (
                    _get_brush(c, 60),   # dim
                    _get_brush(c, 110),  # mid
                    _get_brush(c, 180),  # bright
                )
        for s in self._stars:
            tw = 0.5 + 0.5 * math.sin(s["phase"])
            lo, md, hi = brushes[s["color"]]
            p.setBrush(hi if tw > 0.7 else (md if tw > 0.4 else lo))
            p.drawEllipse(QPointF(s["x"] * W, s["y"] * H), s["size"], s["size"])

    # ----- Top bar -----
    def _draw_top_bar(self, p, x, y, w, h):
        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        p.drawLine(QPointF(x, y + h), QPointF(x + w, y + h))

        # Logo
        p.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        lx, ly = x + 24, y + h / 2
        diamond = QPolygonF([
            QPointF(lx, ly - 8), QPointF(lx + 7, ly),
            QPointF(lx, ly + 8), QPointF(lx - 7, ly),
        ])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.ACCENT, 230)))
        p.drawPolygon(diamond)
        for glow in (4, 2):
            p.setPen(QPen(qcol(C.ACCENT_BR, 50 if glow == 4 else 90), glow))
            p.setFont(QFont("Bahnschrift", 18, QFont.Weight.Bold))
            p.drawText(QRectF(x + 40, y, 200, h),
                       Qt.AlignmentFlag.AlignVCenter, "AEGIS")
        p.setPen(QPen(qcol(C.TEXT, 245), 1))
        p.setFont(QFont("Bahnschrift", 18, QFont.Weight.Bold))
        p.drawText(QRectF(x + 40, y, 200, h),
                   Qt.AlignmentFlag.AlignVCenter, "AEGIS")
        p.setFont(QFont("Bahnschrift", 7, QFont.Weight.Normal))
        p.setPen(QPen(qcol(C.ACCENT_BR, 180), 1))
        p.drawText(QRectF(x + 118, y + h - 16, 80, 12),
                   Qt.AlignmentFlag.AlignLeft, "M-39 / OS")
        p.setFont(QFont("Bahnschrift", 6, QFont.Weight.Normal))
        p.setPen(QPen(qcol(C.TEXT_DIM, 160), 1))
        p.drawText(QRectF(x + 40, y + 10, 100, 10),
                   Qt.AlignmentFlag.AlignLeft, "A . I . C . O . R . E")

        # Tabs (center)
        self._tab_rects = []
        tab_h = 30
        tab_w = 120
        gap = 8
        n = len(self._tabs)
        total = n * tab_w + (n - 1) * gap
        start_x = x + (w - total) / 2
        for i, tab in enumerate(self._tabs):
            tx = start_x + i * (tab_w + gap)
            ty = y + (h - tab_h) / 2
            self._tab_rects.append(QRectF(tx, ty, tab_w, tab_h))
            self._draw_tab(p, tx, ty, tab_w, tab_h, tab, active=(i == self._active_tab))

        # Right: tools counter + system metrics
        rx = x + w - 24
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(rx - 260, y + 8, 90, 14),
                   Qt.AlignmentFlag.AlignRight, "TOOLS")
        p.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT, 230), 1))
        p.drawText(QRectF(rx - 260, y + 22, 90, 26),
                   Qt.AlignmentFlag.AlignRight, f"{self._tools_used:04d}")

        # System metrics (CPU / MEM / UPTIME) before TOOLS
        elapsed = datetime.now() - self._boot_time
        up_str = str(elapsed).split(".")[0]
        hh, mm = divmod(int(elapsed.total_seconds()) // 60, 60)
        ss = int(elapsed.total_seconds()) % 60
        clk = datetime.now().strftime("%H:%M:%S")
        metrics = [
            ("CPU", self._cpu_pct, C.ACCENT,   f"{self._cpu_pct:4.0f}%"),
            ("MEM", self._mem_pct, C.AMBER,    f"{self._mem_pct:4.0f}%"),
            ("UP",  100.0,         C.SUCCESS,  f"{hh:02d}:{mm:02d}:{ss:02d}"),
            ("CLK", 100.0,         C.VIOLET,   clk),
        ]
        mx = rx - 380
        my = y + 10
        for label, pct, color, val in metrics:
            block_w = 88
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
            p.drawText(QRectF(mx, my, block_w, 10),
                       Qt.AlignmentFlag.AlignLeft, label)
            p.setPen(QPen(qcol(C.TEXT, 230), 1))
            p.drawText(QRectF(mx, my, block_w - 4, 10),
                       Qt.AlignmentFlag.AlignRight, val)
            bar_y = my + 14
            bar_h = 4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
            p.drawRoundedRect(QRectF(mx, bar_y, block_w, bar_h), 2, 2)
            fill_w = block_w * (pct / 100.0)
            p.setBrush(QBrush(qcol(color, 220)))
            p.drawRoundedRect(QRectF(mx, bar_y, fill_w, bar_h), 2, 2)
            mx += block_w + 6

        # Settings gear
        sx = x + w - 50
        sy = y + h / 2
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1.5))
        p.setBrush(QBrush(qcol(C.PANEL_HI, 100)))
        p.drawEllipse(QPointF(sx, sy), 10, 10)
        p.setPen(QPen(qcol(C.ACCENT, 180), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(sx, sy), 4, 4)
        for k in range(8):
            ang = k * math.pi / 4 + self._time_phase * 0.3
            x1 = sx + 10 * math.cos(ang)
            y1 = sy + 10 * math.sin(ang)
            x2 = sx + 13 * math.cos(ang)
            y2 = sy + 13 * math.sin(ang)
            p.setPen(QPen(qcol(C.TEXT_DIM, 200), 2))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _draw_tab(self, p, x, y, w, h, text, active=False):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.ACCENT, 35)))
            p.drawPath(path)
            p.setPen(QPen(qcol(C.ACCENT, 220), 1.2))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PANEL_HI, 80)))
            p.drawPath(path)
            p.setPen(QPen(qcol(C.TEXT_DIM, 130), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        color = C.ACCENT_BR if active else C.TEXT_DIM
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol(color, 240 if active else 180), 1))
        p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, text)


    # ----- Left column -----
    def _draw_left_column(self, p, x, y, w, h):
        # Clock + World Time card
        clock_h = 250
        self._draw_clock_panel(p, x + 14, y + 14, w - 28, clock_h)

        # System Health card
        hl_y = y + 14 + clock_h + 14
        hl_h = h - clock_h - 42
        self._draw_system_health(p, x + 14, hl_y, w - 28, hl_h)

    def _draw_clock_panel(self, p, x, y, w, h):
        self._panel(p, x, y, w, h, radius=14)
        now = datetime.now()
        elapsed = now - self._boot_time
        hh, rem = divmod(int(elapsed.total_seconds()) // 60, 60)
        ss = int(elapsed.total_seconds()) % 60
        up_str = f"{hh:02d}:{rem:02d}:{ss:02d}"
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * 2)

        p.setFont(QFont("Courier New", 40, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT, 240), 1))
        p.drawText(QRectF(x + 14, y + 14, w - 28, 56),
                   Qt.AlignmentFlag.AlignCenter, now.strftime("%H:%M:%S"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.ACCENT_BR, int(120 + 100 * pulse))))
        p.drawEllipse(QPointF(x + w - 26, y + 30), 4, 4)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 220), 1))
        p.drawText(QRectF(x + 14, y + 74, w - 28, 16),
                   Qt.AlignmentFlag.AlignCenter, now.strftime("%A   %d %B %Y").upper())

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.SUCCESS, 200), 1))
        p.drawText(QRectF(x + 14, y + 96, w - 28, 14),
                   Qt.AlignmentFlag.AlignCenter, "UPTIME   " + up_str)

        p.setPen(QPen(qcol(C.BORDER, 150), 1))
        p.drawLine(QPointF(x + 24, y + 120), QPointF(x + w - 24, y + 120))

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT, 200), 1))
        p.drawText(QRectF(x + 14, y + 128, 80, 14),
                   Qt.AlignmentFlag.AlignLeft, "WORLD")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
        p.drawText(QRectF(x + 14, y + 128, w - 28, 14),
                   Qt.AlignmentFlag.AlignRight, "LOCAL   UTC+05:30")

        from datetime import timedelta
        zones = [("NYC",  -5, "USA"),
                 ("LDN",   0, "UK"),
                 ("DXB",  +4, "UAE"),
                 ("TYO",  +9, "JPN"),
                 ("SYD", +11, "AUS")]
        row_y = y + 148
        for i, (label, off, country) in enumerate(zones):
            t = (now + timedelta(hours=off)).strftime("%H:%M")
            ry = row_y + i * 18
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.ACCENT_BR, 220), 1))
            p.drawText(QRectF(x + 24, ry, 50, 14),
                       Qt.AlignmentFlag.AlignLeft, label)
            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
            p.drawText(QRectF(x + 70, ry, 60, 14),
                       Qt.AlignmentFlag.AlignLeft, country)
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT, 230), 1))
            p.drawText(QRectF(x + 24, ry, w - 48, 14),
                       Qt.AlignmentFlag.AlignRight, t)

    def _draw_system_health(self, p, x, y, w, h):
        self._panel(p, x, y, w, h, radius=14)
        p.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT, 230), 1))
        p.drawText(QRectF(x + 16, y + 16, 200, 20),
                   Qt.AlignmentFlag.AlignLeft, "System Health")
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * 2.5)
        p.setPen(QPen(qcol(C.SUCCESS, int(180 + 60 * pulse)), 1))
        p.drawText(QRectF(x + 16, y + 16, w - 32, 16),
                   Qt.AlignmentFlag.AlignRight, "● LIVE")
        self._network_ms = getattr(self, "_network_ms", 42.0)
        self._network_ms = max(8.0, min(180.0,
            self._network_ms + random.uniform(-4, 4)))
        cpu_v  = self._cpu_pct
        mem_v  = self._mem_pct
        mic_v  = (self._audio_level * 100) if not self.muted else 0.0
        net_v  = min(100.0, self._network_ms / 2.0)
        items = [
            ("CPU",     cpu_v, "%",  C.ACCENT,    "OK"),
            ("MEMORY",  mem_v, "%",  C.AMBER,     "OK"),
            ("NETWORK", net_v, "ms", C.SUCCESS,   f"{int(self._network_ms)}ms"),
            ("MIC",     mic_v, "%",  C.VIOLET,    "MUTED" if self.muted else "LIVE"),
        ]
        item_y = y + 52
        for label, val, unit, color, status in items:
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT, 220), 1))
            p.drawText(QRectF(x + 16, item_y, 80, 14),
                       Qt.AlignmentFlag.AlignLeft, label)
            p.setFont(QFont("Courier New", 8))
            p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
            p.drawText(QRectF(x + 16, item_y, w - 32, 14),
                       Qt.AlignmentFlag.AlignRight, status)
            bar_y = item_y + 18
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PANEL_DARK, 220)))
            p.drawRoundedRect(QRectF(x + 16, bar_y, w - 32, 5), 2, 2)
            fill_w = (w - 32) * (val / 100.0)
            p.setBrush(QBrush(qcol(color, 220)))
            p.drawRoundedRect(QRectF(x + 16, bar_y, fill_w, 5), 2, 2)
            item_y += 36

        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        p.drawLine(QPointF(x + 16, item_y), QPointF(x + w - 16, item_y))
        item_y += 8

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT_BR, 220), 1))
        p.drawText(QRectF(x + 16, item_y, 200, 14),
                   Qt.AlignmentFlag.AlignLeft, "● Active Context")
        item_y += 18
        ctx_lines = self._build_context_lines()
        p.setFont(QFont("Courier New", 8))
        for line in ctx_lines:
            color = C.TEXT_DIM
            if "OK" in line:    color = C.SUCCESS
            elif "ERR" in line: color = C.DANGER
            elif "RUN" in line: color = C.AMBER
            elif "●" in line:   color = C.ACCENT_BR
            p.setPen(QPen(qcol(color, 220), 1))
            p.drawText(QRectF(x + 18, item_y, w - 36, 14),
                       Qt.AlignmentFlag.AlignLeft, line[:48])
            item_y += 15
            if item_y > y + h - 18:
                break

    def _build_context_lines(self) -> list[str]:
        lines = []
        if self.state == "INITIALISING":
            lines.append("BOOT: subsystems online")
        elif self.state == "LISTENING":
            lines.append("● Voice capture - 16kHz")
            lines.append("OK  : wake-word armed")
        elif self.state == "SPEAKING":
            lines.append("● TTS playback - active")
            lines.append("OK  : audio out stable")
        elif self.state == "THINKING":
            lines.append("● Model inference - 350ms")
            lines.append("OK  : streaming tokens")
        elif self.state == "MUTED":
            lines.append("● Mic muted by user")
        if self._current_tool:
            lines.append("RUN: " + self._current_tool)
        if self._tools_used > 0:
            lines.append("OK  : " + str(self._tools_used) + " tools invoked")
        if not lines:
            lines.append("OK  : all systems nominal")
        return lines[:6]

    def _circle_btn(self, p, cx, cy, r):
        p.setPen(QPen(qcol(C.BORDER, 200), 1))
        p.setBrush(QBrush(qcol(C.PANEL_HI, 150)))
        p.drawEllipse(QPointF(cx, cy), r, r)
        color = C.DANGER if self.muted else C.ACCENT
        p.setPen(QPen(qcol(color, 220), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(cx - 2, cy - 4, 4, 6), 2, 2)
        p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
        p.drawLine(QPointF(cx, cy + 2), QPointF(cx, cy + 4))
        if self.muted:
            p.setPen(QPen(qcol(C.DANGER, 230), 1.5))
            p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))

    def _action_icon(self, p, cx, cy, kind):
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "refresh":
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            p.drawLine(QPointF(cx + 3, cy - 5), QPointF(cx + 6, cy - 3))
            p.drawLine(QPointF(cx + 3, cy - 5), QPointF(cx + 4, cy - 1))
        elif kind == "search":
            p.drawEllipse(QPointF(cx - 1, cy - 1), 5, 5)
            p.drawLine(QPointF(cx + 3, cy + 3), QPointF(cx + 6, cy + 6))
        elif kind == "menu":
            for i in range(3):
                p.drawLine(QPointF(cx - 5, cy - 3 + i * 3),
                           QPointF(cx + 5, cy - 3 + i * 3))
        elif kind == "net":
            for i in range(3):
                p.drawEllipse(QPointF(cx, cy), 7 - i * 2, 7 - i * 2)
        elif kind == "browser":
            p.drawRect(QRectF(cx - 6, cy - 4, 12, 8))
            p.drawLine(QPointF(cx - 6, cy - 1), QPointF(cx + 6, cy - 1))
            p.drawLine(QPointF(cx - 4, cy - 3), QPointF(cx - 2, cy - 3))
        elif kind == "music":
            p.drawLine(QPointF(cx - 3, cy - 5), QPointF(cx - 3, cy + 4))
            p.drawLine(QPointF(cx - 3, cy - 5), QPointF(cx + 3, cy - 6))
            p.drawLine(QPointF(cx + 3, cy - 6), QPointF(cx + 3, cy + 3))
            p.drawEllipse(QPointF(cx - 1, cy + 4), 2.5, 2.5)
            p.drawEllipse(QPointF(cx + 5, cy + 3), 2.5, 2.5)
        elif kind == "reminder":
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy - 3))
            p.drawLine(QPointF(cx, cy), QPointF(cx + 3, cy + 1))
        elif kind == "message":
            p.drawRoundedRect(QRectF(cx - 6, cy - 4, 12, 8), 2, 2)
            p.drawLine(QPointF(cx - 4, cy + 2), QPointF(cx - 2, cy))
            p.drawLine(QPointF(cx + 4, cy + 2), QPointF(cx + 2, cy))
        elif kind == "weather":
            p.drawEllipse(QPointF(cx - 2, cy - 1), 4, 4)
            p.drawEllipse(QPointF(cx + 2, cy - 1), 4, 4)
            p.drawEllipse(QPointF(cx, cy + 2), 4, 4)
            p.drawEllipse(QPointF(cx - 3, cy + 2), 3, 3)
        elif kind == "flight":
            for i in range(3):
                ang = -math.pi / 2 + i * math.pi / 6
                p.drawLine(QPointF(cx, cy),
                           QPointF(cx + 7 * math.cos(ang), cy + 7 * math.sin(ang)))
        elif kind == "notes":
            p.drawRect(QRectF(cx - 4, cy - 5, 8, 10))
            for i in range(3):
                p.drawLine(QPointF(cx - 2, cy - 2 + i * 2),
                           QPointF(cx + 3, cy - 2 + i * 2))


    # ----- Center top (status cards + sphere) -----
    def _draw_center_top(self, p, x, y, w, h):
        # ── LAYOUT: upper = battle station, lower = quick actions grid ──
        margin       = 16
        term_h       = 32
        split_ratio  = 0.55   # upper 55%, lower 45%
        # Upper zone (laptop + compass)
        up_h         = int((h - term_h - margin * 2) * split_ratio)
        # Lower zone (quick actions)
        lo_h         = (h - term_h - margin * 2) - up_h - margin
        up_y         = y + margin
        lo_y         = up_y + up_h + margin

        # ── UPPER: 3D laptop (left) + rotating compass (right) ──
        laptop_w     = 240
        laptop_h     = min(250, up_h - 16)
        laptop_x     = x + 20
        laptop_y     = up_y + (up_h - laptop_h) / 2

        compass_x    = laptop_x + laptop_w + 20
        compass_w    = w - (compass_x - x) - 20
        compass_cy   = up_y + up_h / 2
        compass_R    = min(compass_w / 2 - 20, up_h / 2 - 18, 130)

        # 3D rotating laptop
        self._draw_3d_laptop(p, laptop_x + laptop_w / 2,
                              laptop_y + laptop_h / 2,
                              scale=min(1.0, laptop_h / 250.0))

        # Big battle compass (with integrated plasma reactor inside)
        self._reactor_rect = QRectF(compass_x + compass_w / 2 - compass_R - 4,
                                     compass_cy - compass_R - 4,
                                     compass_R * 2 + 8, compass_R * 2 + 8)
        self._draw_battle_compass(p, compass_x + compass_w / 2, compass_cy, compass_R)

        # Animated data flow lines between laptop and compass
        self._draw_data_flow(p, laptop_x + laptop_w, laptop_y + laptop_h / 2,
                              compass_x, compass_cy)

        # ── LOWER: Pipeline Flow (6-card data processing pipeline) ──
        self._draw_pipeline_flow(p, x + margin, lo_y, w - margin * 2, lo_h)
        # Terminate button at the very bottom
        term_cy = y + h - term_h / 2 - 4
        term_cx = x + w / 2
        self._term_rect = QRectF(term_cx - 65, y + h - term_h, 130, term_h - 8)
        self._draw_corner_brackets(p, self._term_rect, 6, C.DANGER, 220)
        self._terminate_button(p, term_cx, term_cy)

    # ── Pipeline Flow (6-card data processing pipeline) ──────────────
    def _draw_pipeline_flow(self, p, x, y, w, h):
        """Futuristic linear data processing pipeline with 6 agent cards."""
        mode = MODES.get(self._mode, MODES["standard"])
        prim = mode["primary"]
        tp = self._time_phase

        # ── Panel background ──
        panel_path = QPainterPath()
        panel_path.addRoundedRect(QRectF(x, y, w, h), 8, 8)
        p.setPen(QPen(qcol(prim, 60), 1.0))
        p.setBrush(QBrush(qcol("#080c18", 220)))
        p.drawPath(panel_path)

        # Subtle grid
        p.setPen(QPen(qcol(prim, 15), 0.5))
        for gx in range(int(x), int(x + w), 20):
            p.drawLine(QPointF(gx, y), QPointF(gx, y + h))
        for gy in range(int(y), int(y + h), 20):
            p.drawLine(QPointF(x, gy), QPointF(x + w, gy))

        # ── Card definitions ──
        cards = [
            {"title": "The Target",   "sub": "INPUT",       "num": 1, "color": C.ACCENT,    "glow": C.ACCENT},
            {"title": "The Logic",    "sub": "DECISION",     "num": 2, "color": C.ACCENT_BR, "glow": C.ACCENT_BR},
            {"title": "Knowledge",    "sub": "DATABASE",     "num": 3, "color": C.ACCENT_BR, "glow": C.ACCENT_BR},
            {"title": "The Brain",    "sub": "MEMORY",       "num": 4, "color": C.VIOLET,    "glow": C.VIOLET},
            {"title": "Task Core",    "sub": "EXECUTOR",     "num": 5, "color": C.VIOLET,    "glow": C.VIOLET},
            {"title": "The Goal",     "sub": "OUTPUT",       "num": 6, "color": "#ff3a5c",   "glow": "#ff3a5c"},
        ]
        n = len(cards)

        # ── Layout ──
        margin = 8
        top_margin = 8
        card_gap = 8
        arrow_w = 14
        avail_w = w - margin * 2
        card_w = int((avail_w - (n - 1) * (card_gap + arrow_w)) / n)
        card_h = h - top_margin - margin - 6
        card_y = y + top_margin
        card_x_start = x + margin

        # ── Draw flow arrows between cards ──
        for i in range(n - 1):
            c1_x = card_x_start + i * (card_w + card_gap + arrow_w) + card_w
            ax = c1_x + card_gap
            ay = card_y + card_h / 2
            a_end = ax + arrow_w

            p.setPen(QPen(qcol(cards[i]["color"], 60), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(ax, ay), QPointF(a_end, ay))

            head_size = 5
            p.setPen(QPen(qcol(cards[i]["color"], 100), 1.5))
            p.setBrush(QBrush(qcol(cards[i]["color"], 120)))
            arrow = QPolygonF([
                QPointF(a_end, ay),
                QPointF(a_end - head_size, ay - head_size * 0.6),
                QPointF(a_end - head_size, ay + head_size * 0.6),
            ])
            p.drawPolygon(arrow)

            n_particles = 3
            for pi in range(n_particles):
                t = ((tp * 1.5 + pi / n_particles) % 1.0)
                px = ax + t * arrow_w
                py = ay + 4 * math.sin(t * math.tau + tp)
                pr = 1.5 + 1.0 * math.sin(tp * 3 + pi)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(qcol(cards[i]["color"], int(180 + 75 * math.sin(tp * 2 + pi)))))
                p.drawEllipse(QPointF(px, py), pr, pr)

        # ── Draw each card ──
        for i, card in enumerate(cards):
            cx = card_x_start + i * (card_w + card_gap + arrow_w)
            cy = card_y
            cw = card_w
            ch = card_h
            col = card["color"]
            card_rect = QRectF(cx, cy, cw, ch)

            glow_pulse = 0.6 + 0.4 * math.sin(tp * 2.5 + i * 0.8)

            card_path = QPainterPath()
            card_path.addRoundedRect(card_rect, 6, 6)
            p.setPen(QPen(qcol(col, int(80 + 60 * glow_pulse)), 1.2))
            card_bg = QLinearGradient(cx, cy, cx, cy + ch)
            card_bg.setColorAt(0.0, qcol(col, 20))
            card_bg.setColorAt(0.5, qcol("#0e1525", 200))
            card_bg.setColorAt(1.0, qcol(col, 10))
            p.setBrush(QBrush(card_bg))
            p.drawPath(card_path)

            line_rect = QRectF(cx + 6, cy + 2, cw - 12, 2)
            line_grad = QLinearGradient(cx + 6, cy, cx + cw - 6, cy)
            line_grad.setColorAt(0.0, qcol(col, 0))
            line_grad.setColorAt(0.5, qcol(col, int(200 * glow_pulse)))
            line_grad.setColorAt(1.0, qcol(col, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(line_grad))
            p.drawRoundedRect(line_rect, 1, 1)

            # ── Icon ──
            icon_cx = cx + cw / 2
            icon_y = cy + 16
            icon_size = 18

            if i == 0:  # Bullseye
                p.setPen(QPen(qcol(col, 180), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(icon_cx, icon_y), icon_size, icon_size)
                p.drawEllipse(QPointF(icon_cx, icon_y), icon_size * 0.6, icon_size * 0.6)
                p.drawEllipse(QPointF(icon_cx, icon_y), icon_size * 0.25, icon_size * 0.25)
                p.drawLine(QPointF(icon_cx - icon_size * 1.2, icon_y),
                           QPointF(icon_cx + icon_size * 1.2, icon_y))
                p.drawLine(QPointF(icon_cx, icon_y - icon_size * 1.2),
                           QPointF(icon_cx, icon_y + icon_size * 1.2))

            elif i == 1:  # Logic gate (AND)
                gs = icon_size
                gpath = QPainterPath()
                gpath.moveTo(icon_cx - gs, icon_y - gs * 0.7)
                gpath.lineTo(icon_cx - gs, icon_y + gs * 0.7)
                gpath.lineTo(icon_cx, icon_y + gs * 0.7)
                gpath.cubicTo(icon_cx + gs * 0.8, icon_y + gs * 0.7,
                             icon_cx + gs * 0.8, icon_y - gs * 0.7,
                             icon_cx, icon_y - gs * 0.7)
                gpath.closeSubpath()
                p.setPen(QPen(qcol(col, 180), 1.2))
                p.setBrush(QBrush(qcol(col, 30)))
                p.drawPath(gpath)

            elif i == 2:  # Database (stacked cylinders)
                db_w = icon_size * 1.4
                db_h = icon_size * 0.6
                for di in range(3):
                    dby = icon_y - db_h * 0.6 + di * db_h * 0.5
                    db_path = QPainterPath()
                    db_path.addRoundedRect(QRectF(icon_cx - db_w / 2, dby, db_w, db_h), db_h / 2, db_h / 2)
                    p.setPen(QPen(qcol(col, int(140 - di * 20)), 1.0))
                    p.setBrush(QBrush(qcol(col, int(25 - di * 5))))
                    p.drawPath(db_path)

            elif i == 3:  # Brain with circuits
                br = icon_size
                p.setPen(QPen(qcol(col, 160), 1.2))
                p.setBrush(QBrush(qcol(col, 25)))
                p.drawEllipse(QPointF(icon_cx - br * 0.35, icon_y), br * 0.55, br * 0.8)
                p.drawEllipse(QPointF(icon_cx + br * 0.35, icon_y), br * 0.55, br * 0.8)
                p.setPen(QPen(qcol(col, 100), 0.8))
                p.drawLine(QPointF(icon_cx - br * 0.8, icon_y - br * 0.3),
                          QPointF(icon_cx - br * 1.3, icon_y - br * 0.1))
                p.drawLine(QPointF(icon_cx + br * 0.8, icon_y + br * 0.3),
                          QPointF(icon_cx + br * 1.3, icon_y + br * 0.1))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(qcol(col, 180)))
                p.drawEllipse(QPointF(icon_cx - br * 1.3, icon_y - br * 0.1), 2, 2)
                p.drawEllipse(QPointF(icon_cx + br * 1.3, icon_y + br * 0.1), 2, 2)

            elif i == 4:  # Gear
                g = icon_size
                p.setPen(QPen(qcol(col, 160), 1.2))
                p.setBrush(QBrush(qcol(col, 25)))
                p.drawEllipse(QPointF(icon_cx, icon_y), g * 0.7, g * 0.7)
                p.setPen(QPen(qcol(col, 140), 1.5))
                for ti in range(8):
                    ta = ti * math.tau / 8 + tp * 0.5
                    tx1 = icon_cx + g * 0.7 * math.cos(ta)
                    ty1 = icon_y + g * 0.7 * math.sin(ta)
                    tx2 = icon_cx + g * 0.95 * math.cos(ta)
                    ty2 = icon_y + g * 0.95 * math.sin(ta)
                    p.drawLine(QPointF(tx1, ty1), QPointF(tx2, ty2))
                p.setPen(QPen(qcol(col, 100), 0.8))
                p.setBrush(QBrush(qcol("#0e1525", 200)))
                p.drawEllipse(QPointF(icon_cx, icon_y), g * 0.3, g * 0.3)

            elif i == 5:  # Rocket
                rk = icon_size * 1.1
                rpath = QPainterPath()
                rpath.moveTo(icon_cx, icon_y - rk)
                rpath.lineTo(icon_cx - rk * 0.4, icon_y + rk * 0.2)
                rpath.lineTo(icon_cx - rk * 0.15, icon_y + rk * 0.2)
                rpath.lineTo(icon_cx - rk * 0.15, icon_y + rk * 0.7)
                rpath.lineTo(icon_cx + rk * 0.15, icon_y + rk * 0.7)
                rpath.lineTo(icon_cx + rk * 0.15, icon_y + rk * 0.2)
                rpath.lineTo(icon_cx + rk * 0.4, icon_y + rk * 0.2)
                rpath.closeSubpath()
                p.setPen(QPen(qcol(col, 180), 1.2))
                p.setBrush(QBrush(qcol(col, 30)))
                p.drawPath(rpath)
                flame = QPainterPath()
                flame.moveTo(icon_cx - rk * 0.1, icon_y + rk * 0.7)
                flame.cubicTo(icon_cx - rk * 0.2, icon_y + rk * 1.0 + 4 * math.sin(tp * 4),
                             icon_cx + rk * 0.2, icon_y + rk * 1.0 + 4 * math.sin(tp * 4 + 1),
                             icon_cx + rk * 0.1, icon_y + rk * 0.7)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(qcol(col, 120)))
                p.drawPath(flame)

            # ── Title ──
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(col, 220), 1))
            title_rect = QRectF(cx + 2, icon_y + 16, cw - 4, 14)
            p.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       card["title"])

            # ── Subtitle ──
            p.setFont(QFont("Consolas", 5))
            p.setPen(QPen(qcol(col, 120), 1))
            sub_rect = QRectF(cx + 2, icon_y + 28, cw - 4, 10)
            p.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       card["sub"])

            # ── Status indicator ──
            agent_keys = ["target", "logic", "knowledge", "brain", "executor", "validator"]
            status = self._agent_status.get(agent_keys[i], "idle")
            status_color = {
                "running": "#ffb347",
                "completed": "#4ade80",
                "failed": "#ff3a5c",
            }.get(status, C.TEXT_DIM)

            # Animated pulse when running
            if status == "running":
                pulse_r = 2.5 + 1.5 * math.sin(tp * 6 + i * 1.5)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(qcol(status_color, int(100 + 80 * math.sin(tp * 5 + i)))))
                p.drawEllipse(QPointF(cx + cw - 8, cy + 8), pulse_r, pulse_r)

            # Status text
            p.setFont(QFont("Consolas", 5))
            p.setPen(QPen(qcol(status_color, 200), 1))
            status_rect = QRectF(cx + cw - 40, cy + 6, 36, 8)
            p.drawText(status_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       status.upper())

            # ── Agent status data ──
            status_texts = [
                ["target", "logic", "knowledge", "brain", "executor", "validator"],
            ]
            display_texts = []
            for sk in agent_keys:
                s = self._agent_status.get(sk, "⏳ idle")
                if s == "running":
                    display_texts.append("▶ running")
                elif s == "completed":
                    display_texts.append("✓ done")
                elif "failed" in s:
                    display_texts.append("✗ failed")
                else:
                    display_texts.append("○ standby")

            p.setFont(QFont("Consolas", 5))
            p.setPen(QPen(qcol(C.TEXT_DIM, 140), 1))
            dr = QRectF(cx + 4, icon_y + 36, cw - 8, 8)
            p.drawText(dr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       display_texts[i])

            # ── Glowing number circle at bottom ──
            num_y = cy + ch - 12
            num_r = 8
            num_glow = 0.7 + 0.3 * math.sin(tp * 3 + i * 1.2)
            p.setPen(QPen(qcol(col, int(180 + 75 * num_glow)), 1.2))
            p.setBrush(QBrush(qcol(col, int(20 + 15 * num_glow))))
            p.drawEllipse(QPointF(icon_cx, num_y), num_r, num_r)
            p.setFont(QFont("Consolas", 6, QFont.Weight.Bold))
            p.setPen(QPen(qcol(col, 230), 1))
            p.drawText(QRectF(icon_cx - num_r, num_y - num_r, num_r * 2, num_r * 2),
                       Qt.AlignmentFlag.AlignCenter, str(card["num"]))


    # ── Dynamic Island (mode container) ──────────────────────────────
    def _draw_dynamic_island(self, p, x, y, w):
        """Top-of-centre floating pill that hosts the mini arc reactor + label.
        Drawn only when a non-standard mode is active."""
        mode = MODES[self._mode]
        prim = mode["primary"]
        sec  = mode["secondary"]
        acc  = mode["accent"]

        # ── Sizing & eased enter animation (spring-out) ───────────────
        anim = self._mode_anim_t
        # overshoot then settle: 0 → 1.08 → 0.96 → 1.0
        if   anim < 0.6: scale = 1.0 + 0.08 * (anim / 0.6)
        elif anim < 0.85: scale = 1.08 - 0.12 * ((anim - 0.6) / 0.25)
        else: scale = 0.96 + 0.04 * ((anim - 0.85) / 0.15)
        base_w = 380
        pill_w = base_w * scale
        pill_h = ISLAND_H * scale
        cx = x + w / 2
        cy = y + pill_h / 2 + 4 * (1 - anim)  # drops in from above
        rect = QRectF(cx - pill_w / 2, cy - pill_h / 2, pill_w, pill_h)
        self._island_rect = rect

        # ── Soft outer glow (mode-tinted) ────────────────────────────
        glow = QRadialGradient(QPointF(cx, cy), pill_w * 0.7)
        glow.setColorAt(0.0, qcol(prim, 70))
        glow.setColorAt(0.6, qcol(prim, 30))
        glow.setColorAt(1.0, qcol(prim, 0))
        p.fillRect(QRectF(cx - pill_w, cy - pill_h, pill_w * 2, pill_h * 2), QBrush(glow))

        # ── Pill body — dark base with subtle gradient ────────────────
        body_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        body_grad.setColorAt(0.0, qcol("#0c1422", 235))
        body_grad.setColorAt(0.5, qcol("#0a1020", 245))
        body_grad.setColorAt(1.0, qcol("#070b14", 235))
        path = QPainterPath()
        path.addRoundedRect(rect, pill_h / 2, pill_h / 2)
        p.fillPath(path, QBrush(body_grad))

        # ── Mode-tinted top border stroke ─────────────────────────────
        border_grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        border_grad.setColorAt(0.0, qcol(prim, 0))
        border_grad.setColorAt(0.15, qcol(prim, 180))
        border_grad.setColorAt(0.5, qcol(acc, 240))
        border_grad.setColorAt(0.85, qcol(prim, 180))
        border_grad.setColorAt(1.0, qcol(prim, 0))
        p.setPen(QPen(QBrush(border_grad), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # ── Inner highlight (top reflection) ──────────────────────────
        hi = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + pill_h * 0.6)
        hi.setColorAt(0.0, qcol(prim, 35))
        hi.setColorAt(1.0, qcol(prim, 0))
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, rect.height() - 2),
                            pill_h / 2 - 1, pill_h / 2 - 1)
        p.save()
        p.setClipPath(clip)
        p.fillRect(rect, QBrush(hi))
        p.restore()

        # ── Mini arc reactor (left) ───────────────────────────────────
        reactor_cx = rect.left() + 24
        reactor_cy = cy
        self._draw_mini_arc_reactor(p, reactor_cx, reactor_cy, 14, prim, sec, acc)

        # ── Mode label (centre) ───────────────────────────────────────
        label = mode["name"]
        tagline = mode["tagline"]
        # tiny dot indicator on left of label
        dot_x = reactor_cx + 22
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * mode["speed"] * 4.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(prim, 180 + int(70 * pulse))))
        p.drawEllipse(QPointF(dot_x, cy), 2.2, 2.2)

        font_lbl = _get_font("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(font_lbl)
        p.setPen(QPen(qcol(acc, 255)))
        p.drawText(QPointF(dot_x + 10, cy - 2), label)
        # small "·" + tagline below in dimmer
        p.setFont(_get_font("Segoe UI", 8, QFont.Weight.Normal))
        p.setPen(QPen(qcol(prim, 200)))
        tag_w = p.fontMetrics().horizontalAdvance(tagline)
        p.drawText(QPointF(cx - tag_w / 2, cy + 11), tagline)

        # ── Audio meter (right) ───────────────────────────────────────
        bar_x0 = rect.right() - 64
        bar_y  = cy - 8
        for i in range(5):
            bx = bar_x0 + i * 7
            level = max(self._audio_level, 0.05 + 0.04 * i)
            phase = self._time_phase * mode["speed"] * 8 + i * 0.7
            lvl = max(0.15, min(1.0, level + 0.18 * math.sin(phase)))
            bh = 16 * lvl
            col = acc if lvl > 0.7 else prim
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(col, 220 if i == 4 else 170)))
            p.drawRoundedRect(QRectF(bx, bar_y + (16 - bh) / 2, 4, bh), 1.5, 1.5)

        # ── Close button (×) ──────────────────────────────────────────
        close_size = 18
        close_cx   = rect.right() - 18
        close_cy   = cy
        close_rect = QRectF(close_cx - close_size / 2, close_cy - close_size / 2,
                            close_size, close_size)
        self._island_close_rect = close_rect
        p.setPen(QPen(qcol(prim, 180), 1.2))
        p.setBrush(QBrush(qcol("#0a0f1c", 200)))
        p.drawEllipse(close_rect)
        s = 4
        p.setPen(QPen(qcol(prim, 220), 1.3))
        p.drawLine(QPointF(close_cx - s, close_cy - s), QPointF(close_cx + s, close_cy + s))
        p.drawLine(QPointF(close_cx + s, close_cy - s), QPointF(close_cx - s, close_cy + s))

        # ── Corner brackets — only on top-left/bottom-right (subtle) ──
        p.setPen(QPen(qcol(prim, 170), 1.0))
        br = 5
        # top-left
        p.drawLine(QPointF(rect.left() + 6, rect.top() + 2), QPointF(rect.left() + 6, rect.top() + 6))
        p.drawLine(QPointF(rect.left() + 6, rect.top() + 2), QPointF(rect.left() + 10, rect.top() + 2))
        # bottom-right
        p.drawLine(QPointF(rect.right() - 6, rect.bottom() - 2), QPointF(rect.right() - 6, rect.bottom() - 6))
        p.drawLine(QPointF(rect.right() - 6, rect.bottom() - 2), QPointF(rect.right() - 10, rect.bottom() - 2))

    def _draw_mini_arc_reactor(self, p, cx, cy, R, prim, sec, acc):
        """A small voice-reactive arc reactor. R = base radius."""
        mode = MODES[self._mode]
        speed = mode["speed"]
        # Voice-reactive radius
        audio = self._audio_level
        r = R * (1.0 + 0.32 * audio + 0.05 * math.sin(self._time_phase * speed * 6))

        # Outer glow
        glow = QRadialGradient(QPointF(cx, cy), r * 2.2)
        glow.setColorAt(0.0, qcol(prim, 110))
        glow.setColorAt(0.5, qcol(prim, 50))
        glow.setColorAt(1.0, qcol(prim, 0))
        p.fillRect(QRectF(cx - r * 2.5, cy - r * 2.5, r * 5, r * 5), QBrush(glow))

        # Outermost ring (rotating)
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(self._time_phase * speed * 30))
        p.setPen(QPen(qcol(prim, 140), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r * 1.18, r * 1.18)
        # tick marks around
        for i in range(8):
            a = i * math.pi / 4
            x1 = (r * 1.18) * math.cos(a)
            y1 = (r * 1.18) * math.sin(a)
            x2 = (r * 1.30) * math.cos(a)
            y2 = (r * 1.30) * math.sin(a)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        p.restore()

        # Mid ring (counter-rotating)
        p.save()
        p.translate(cx, cy)
        p.rotate(-math.degrees(self._time_phase * speed * 45))
        p.setPen(QPen(qcol(sec, 180), 1.0))
        p.drawEllipse(QPointF(0, 0), r, r)
        # 3 triangular arcs
        for i in range(3):
            a0 = i * math.tau / 3 + self._time_phase * speed * 1.5
            a1 = a0 + 0.55
            x0 = r * math.cos(a0); y0 = r * math.sin(a0)
            x1 = r * math.cos(a1); y1 = r * math.sin(a1)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        p.restore()

        # Inner core (pulsing with voice)
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * speed * 5.0)
        core_r = r * 0.45 * (1.0 + 0.25 * audio)
        core_grad = QRadialGradient(QPointF(cx, cy), core_r)
        core_grad.setColorAt(0.0, qcol("#ffffff", int(220 + 35 * audio)))
        core_grad.setColorAt(0.4, qcol(acc, 230))
        core_grad.setColorAt(1.0, qcol(prim, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Bright pinpoint at center
        p.setBrush(QBrush(qcol("#ffffff", int(200 + 55 * audio))))
        p.drawEllipse(QPointF(cx, cy), core_r * 0.30, core_r * 0.30)

    def _draw_island_scan(self, p):
        """Subtle horizontal scan line that crosses the island — sells the 'alive' feel."""
        if not self._mode_anim_t < 1.0:
            pass
        rect = self._island_rect
        if rect.isEmpty():
            return
        mode = MODES[self._mode]
        prim = mode["primary"]
        # scan x position
        sx = rect.left() + (rect.width() * (0.5 + 0.5 * math.sin(self._time_phase * 1.2)))
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        grad.setColorAt(0.0, qcol(prim, 0))
        grad.setColorAt(0.5, qcol(prim, 35))
        grad.setColorAt(1.0, qcol(prim, 0))
        p.setPen(QPen(QBrush(grad), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(sx, rect.top() + 2), QPointF(sx, rect.bottom() - 2))

    # ────────────────────────────────────────────────────────────────
    # DYNAMIC PANEL — full iOS-style multi-card island
    # ────────────────────────────────────────────────────────────────
    def _update_card_anims(self):
        """Per-frame: advance animation timers, update card heights,
        and trigger auto-remove when TTL expires."""
        speed_scale = MODES[self._mode]["speed"] if self._mode in MODES else 1.0
        now = time.time()
        for c in self._pinned_cards:
            st = c["anim_state"]
            if st == "entering":
                c["anim_t"] = min(1.0, c["anim_t"] + 0.045 / max(0.4, speed_scale))
                if c["anim_t"] >= 1.0:
                    c["anim_state"] = "pinned"
                    c["anim_t"] = 0.0
            elif st == "leaving":
                c["anim_t"] = min(1.0, c["anim_t"] + 0.06)
            elif st == "pulse":
                c["anim_t"] = min(1.0, c["anim_t"] + 0.08)
                if c["anim_t"] >= 1.0:
                    c["anim_state"] = "pinned"
                    c["anim_t"] = 0.0
            # Auto-remove: TTL fires from any non-leaving state (entering/pinned/pulse)
            if st != "leaving" and c.get("auto_remove_at", 0) > 0:
                if now >= c["auto_remove_at"]:
                    c["anim_state"] = "leaving"
                    c["anim_t"]     = 0.0

    def _card_target_h(self, c: dict) -> float:
        """Target height of a single card (used during enter/leave)."""
        t = c["type"]
        if t in ("search", "results"):
            n = min(len(c["data"].get("results", [])), 3)
            return 60 + n * 22
        if t in ("music", "stock", "weather", "timer", "note", "reminder", "task", "news", "quote"):
            return 100
        return 86

    def _ease_out_back(self, t: float) -> float:
        # smooth overshoot — 0..1 → 0..1.05..1
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

    def _draw_dynamic_panel(self, p, x, y, w, h):
        """Main entry — pill at top, cards area below."""
        mode = MODES[self._mode]
        prim = mode["primary"]
        sec  = mode["secondary"]
        acc  = mode["accent"]

        # ── Panel background — subtle mode-tinted ─────────────────────
        bg_grad = QLinearGradient(x, y, x, y + h)
        bg_grad.setColorAt(0.0, qcol(prim, 8))
        bg_grad.setColorAt(0.5, qcol(prim, 4))
        bg_grad.setColorAt(1.0, qcol(prim, 0))
        p.fillRect(QRectF(x, y, w, h), QBrush(bg_grad))

        # ── Holographic sci-fi background layers ──────────────────────
        self._draw_panel_sci_fi_bg(p, x, y, w, h, mode)

        # ── Pill at top ────────────────────────────────────────────────
        pill_w = 380
        pill_h = ISLAND_H
        pill_x = x + (w - pill_w) / 2
        pill_y = y + 8
        self._draw_panel_pill(p, pill_x, pill_y, pill_w, pill_h)

        # ── Cards area below pill (only when expanded) ────────────────
        self._card_close_rects.clear()
        self._card_action_rects.clear()
        if not self._panel_expanded:
            p.setFont(_get_font("Segoe UI", 9))
            p.setPen(QPen(qcol(prim, 140)))
            p.drawText(QRectF(x, pill_y + pill_h + 12, w, 20),
                       Qt.AlignmentFlag.AlignCenter, "▼ TAP PILL TO EXPAND ▼")
            self._draw_panel_sci_fi_foreground(p, x, y, w, h, mode)
            return

        # Expanded — layout the cards
        cards_x = x + 20
        cards_y = pill_y + pill_h + 18
        cards_w = w - 40
        cards_h = h - (cards_y - y) - 14

        # Adjust card visibility count by available height
        saved_max = self._card_max_visible
        target_h = 110
        max_fit = max(1, (cards_h - 30) // (target_h + 10))
        if max_fit < saved_max:
            self._card_max_visible = max_fit

        if not self._pinned_cards:
            self._draw_panel_empty_state(p, cards_x, cards_y, cards_w, cards_h, mode)
            self._draw_panel_sci_fi_foreground(p, x, y, w, h, mode)
            return

        # Draw cards with vertical scroll
        visible = self._pinned_cards[self._card_scroll:self._card_scroll + self._card_max_visible]
        cur_y = cards_y
        for c in visible:
            h_target = self._card_target_h(c)
            if c["anim_state"] == "entering":
                e = self._ease_out_back(c["anim_t"])
                c["h"] = h_target * max(0.0, min(1.0, e))
            elif c["anim_state"] == "leaving":
                c["h"] = h_target * (1.0 - c["anim_t"])
            else:
                c["h"] = h_target
            if c["h"] < 1:
                continue
            self._draw_pinned_card(p, c, cards_x, cur_y, cards_w, c["h"])
            cur_y += c["h"] + 10

        # Scrollbar if more cards than fit
        if len(self._pinned_cards) > self._card_max_visible:
            self._draw_panel_scrollbar(p, cards_x, cards_y, cards_w, cards_h)

        # Restore max_visible (in case we shrunk it)
        self._card_max_visible = saved_max

        # Foreground sci-fi effects (scan line, particles, ticker)
        self._draw_panel_sci_fi_foreground(p, x, y, w, h, mode)

    # ── Sci-fi panel layers ───────────────────────────────────────────
    def _draw_panel_sci_fi_bg(self, p, x, y, w, h, mode):
        prim = mode["primary"]; acc = mode["accent"]; sec = mode["secondary"]
        try:
            # Holographic flicker (subtle, 0.92-1.0 alpha modulation)
            flicker = 0.96 + 0.04 * math.sin(self._time_phase * 8.3) + 0.02 * math.sin(self._time_phase * 17.1)
            # Outer soft glow that pulses with mode color
            glow = QRadialGradient(QPointF(x + w / 2, y + h / 2), max(w, h) * 0.7)
            glow.setColorAt(0.0, qcol(prim, int(28 * flicker)))
            glow.setColorAt(0.5, qcol(prim, int(14 * flicker)))
            glow.setColorAt(1.0, qcol(prim, 0))
            p.fillRect(QRectF(x, y, w, h), QBrush(glow))
            # Corner grid lines (sci-fi frame)
            p.setPen(QPen(qcol(prim, int(80 * flicker)), 1.0))
            m = 18
            for (bx, by, dx, dy) in [
                (x + 8,         y + 8,         1,  1),
                (x + w - 8,     y + 8,        -1,  1),
                (x + 8,         y + h - 8,     1, -1),
                (x + w - 8,     y + h - 8,    -1, -1),
            ]:
                p.drawLine(QPointF(bx, by), QPointF(bx + m * dx, by))
                p.drawLine(QPointF(bx, by), QPointF(bx, by + m * dy))
            # Hex grid (sparse — 64px step, ~100 dots per frame even at 1440x900)
            step = 64
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(prim, int(24 * flicker))))
            for gx in range(int(x) + step, int(x + w), step):
                for gy in range(int(y) + step, int(y + h), step * 2):
                    p.drawEllipse(QPointF(gx + (gy // step) % 2 * (step / 2), gy), 0.9, 0.9)
            # Edge scan band — vertical band of light that moves horizontally
            sx = x + (w * (0.5 + 0.5 * math.sin(self._time_phase * 0.6)))
            band = QLinearGradient(sx - 80, 0, sx + 80, 0)
            band.setColorAt(0.0, qcol(prim, 0))
            band.setColorAt(0.5, qcol(acc, 30))
            band.setColorAt(1.0, qcol(prim, 0))
            p.fillRect(QRectF(x, y, w, h), QBrush(band))
        except Exception:
            pass

    def _draw_panel_sci_fi_foreground(self, p, x, y, w, h, mode):
        prim = mode["primary"]; acc = mode["accent"]
        try:
            # Horizontal moving scan line (full width)
            sy = y + (h * (0.5 + 0.5 * math.sin(self._time_phase * 1.1)))
            scan_grad = QLinearGradient(0, sy - 14, 0, sy + 14)
            scan_grad.setColorAt(0.0, qcol(prim, 0))
            scan_grad.setColorAt(0.5, qcol(prim, 55))
            scan_grad.setColorAt(1.0, qcol(prim, 0))
            p.setPen(QPen(QBrush(scan_grad), 1.0))
            p.drawLine(QPointF(x, sy), QPointF(x + w, sy))
            # Floating data dots — initialised once, cheap on subsequent frames
            if getattr(self, "_sci_fi_particles", None) is None:
                self._sci_fi_particles = [
                    (random.random(), random.random(), random.uniform(0.4, 1.0))
                    for _ in range(16)
                ]
            tp = self._time_phase
            for px_f, py_f, spd in self._sci_fi_particles:
                px = x + ((px_f + tp * 0.05 * spd) % 1.0) * w
                py = y + ((py_f + tp * 0.02 * spd) % 1.0) * h
                r  = 0.8 + 0.6 * math.sin(tp * 2 + px_f * 7)
                a  = int(60 + 80 * (0.5 + 0.5 * math.sin(tp * 1.5 + py_f * 5)))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(qcol(acc, a)))
                p.drawEllipse(QPointF(px, py), r, r)
            # Ticker text at very bottom
            ticker_msgs = (
                "SYS: DYNAMIC ISLAND ACTIVE",
                "AI: NEURAL LINK STABLE",
                "LINK: 42ms  ·  124.7.62.18",
                "MEM: 38%  ·  CPU: 12%  ·  NET: 98%",
                "MODE: " + mode["name"] + "  ·  " + mode["tagline"],
                "// READY  //  LISTENING  //  AWAITING INPUT //",
            )
            idx = int(self._time_phase * 0.4) % len(ticker_msgs)
            msg = ticker_msgs[idx]
            p.setFont(_get_font("Consolas", 8))
            p.setPen(QPen(qcol(prim, 110)))
            p.drawText(QRectF(x + 12, h - 18, w - 24, 14),
                       Qt.AlignmentFlag.AlignLeft, msg)
            # Corner ID labels
            p.setFont(_get_font("Consolas", 7))
            p.setPen(QPen(qcol(prim, 90)))
            p.drawText(QPointF(x + 12, y + 14), "▮ DYNAMIC.ISLAND/" + self._mode.upper())
            p.drawText(QPointF(x + w - 12 - 100, y + 14), "[T+{:06.1f}s]".format(self._time_phase))
        except Exception:
            pass

    def _draw_panel_empty_state(self, p, x, y, w, h, mode):
        prim = mode["primary"]; acc = mode["accent"]
        # Centered icon + text
        cx = x + w / 2
        cy = y + h / 2
        # Icon — outlined square with sparkle
        p.setPen(QPen(qcol(prim, 90), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(cx - 40, cy - 50, 80, 80), 14, 14)
        # plus sign
        p.setPen(QPen(qcol(prim, 130), 1.6))
        p.drawLine(QPointF(cx - 8, cy - 10), QPointF(cx + 8, cy - 10))
        p.drawLine(QPointF(cx, cy - 18), QPointF(cx, cy - 2))
        # text
        p.setFont(_get_font("Segoe UI", 11, QFont.Weight.Bold))
        p.setPen(QPen(qcol(acc, 220)))
        p.drawText(QRectF(x, cy + 40, w, 22), Qt.AlignmentFlag.AlignCenter, "DYNAMIC ISLAND READY")
        p.setFont(_get_font("Segoe UI", 9))
        p.setPen(QPen(qcol(prim, 160)))
        p.drawText(QRectF(x, cy + 62, w, 18), Qt.AlignmentFlag.AlignCenter,
                   "Ask me anything — results pin here automatically")
        # corner brackets
        p.setPen(QPen(qcol(prim, 100), 1.0))
        for (bx, by, dx, dy) in [(x+8, y+8, 1, 1), (x+w-8, y+8, -1, 1),
                                 (x+8, y+h-8, 1, -1), (x+w-8, y+h-8, -1, -1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + 12*dx, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + 12*dy))

    def _draw_panel_scrollbar(self, p, x, y, w, h):
        # Right edge
        sb_x = x + w - 4
        sb_h = h
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol("#1a2230", 180)))
        p.drawRoundedRect(QRectF(sb_x, y, 4, sb_h), 2, 2)
        # Thumb
        total = len(self._pinned_cards)
        visible_n = self._card_max_visible
        thumb_h = max(20, sb_h * visible_n / total)
        track_n = total - visible_n
        if track_n > 0:
            t = self._card_scroll / track_n
        else:
            t = 0
        thumb_y = y + (sb_h - thumb_h) * t
        self._cards_scrollbar_rect   = QRectF(sb_x, y, 4, sb_h)
        self._cards_scrollbar_thumb  = QRectF(sb_x, thumb_y, 4, thumb_h)
        p.setBrush(QBrush(qcol(MODES[self._mode]["primary"], 220)))
        p.drawRoundedRect(self._cards_scrollbar_thumb, 2, 2)

    def _draw_panel_pill(self, p, x, y, w, h):
        """Pill = the iOS-Dynamic-Island compact header."""
        mode = MODES[self._mode]
        prim = mode["primary"]; sec = mode["secondary"]; acc = mode["accent"]
        # Drop-in animation
        anim = self._mode_anim_t
        if   anim < 0.6: scale = 1.0 + 0.08 * (anim / 0.6)
        elif anim < 0.85: scale = 1.08 - 0.12 * ((anim - 0.6) / 0.25)
        else: scale = 0.96 + 0.04 * ((anim - 0.85) / 0.15)
        pw = w * scale
        ph = h * scale
        cx = x + w / 2
        cy = y + h / 2 + 4 * (1 - anim)
        rect = QRectF(cx - pw / 2, cy - ph / 2, pw, ph)
        self._island_rect = rect

        # Outer glow
        glow = QRadialGradient(QPointF(cx, cy), pw * 0.7)
        glow.setColorAt(0.0, qcol(prim, 70))
        glow.setColorAt(0.6, qcol(prim, 30))
        glow.setColorAt(1.0, qcol(prim, 0))
        p.fillRect(QRectF(cx - pw, cy - ph, pw * 2, ph * 2), QBrush(glow))

        # Body
        body_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        body_grad.setColorAt(0.0, qcol("#0c1422", 240))
        body_grad.setColorAt(0.5, qcol("#0a1020", 250))
        body_grad.setColorAt(1.0, qcol("#070b14", 240))
        path = QPainterPath()
        path.addRoundedRect(rect, ph / 2, ph / 2)
        p.fillPath(path, QBrush(body_grad))

        # Border
        bg = QLinearGradient(rect.left(), 0, rect.right(), 0)
        bg.setColorAt(0.0, qcol(prim, 0))
        bg.setColorAt(0.15, qcol(prim, 180))
        bg.setColorAt(0.5, qcol(acc, 240))
        bg.setColorAt(0.85, qcol(prim, 180))
        bg.setColorAt(1.0, qcol(prim, 0))
        p.setPen(QPen(QBrush(bg), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Inner highlight
        hi = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + ph * 0.6)
        hi.setColorAt(0.0, qcol(prim, 35))
        hi.setColorAt(1.0, qcol(prim, 0))
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, rect.height() - 2),
                            ph / 2 - 1, ph / 2 - 1)
        p.save()
        p.setClipPath(clip)
        p.fillRect(rect, QBrush(hi))
        p.restore()

        # Mini arc reactor (left)
        rcx = rect.left() + 22
        rcy = cy
        self._draw_mini_arc_reactor(p, rcx, rcy, 12, prim, sec, acc)

        # Centre: status dot + mode label + tagline
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * mode["speed"] * 4.0)
        dot_x = rcx + 20
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(prim, 180 + int(70 * pulse))))
        p.drawEllipse(QPointF(dot_x, cy), 2.2, 2.2)

        # mode name (bold) + tagline (small below)
        p.setFont(_get_font("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol(acc, 255)))
        p.drawText(QPointF(dot_x + 8, cy - 2), mode["name"])

        # right side: audio bars + collapse btn + close btn
        bar_x0 = rect.right() - 78
        for i in range(5):
            bx = bar_x0 + i * 6
            lvl = max(0.15, min(1.0, self._audio_level + 0.18 * math.sin(self._time_phase * mode["speed"] * 8 + i * 0.7)))
            bh = 14 * lvl
            col = acc if lvl > 0.7 else prim
            p.setBrush(QBrush(qcol(col, 220 if i == 4 else 170)))
            p.drawRoundedRect(QRectF(bx, cy - bh / 2, 3, bh), 1.2, 1.2)

        # collapse / expand arrow
        ar_x = rect.right() - 36
        ar_y = cy
        ar_size = 6
        arrow_path = QPainterPath()
        if self._panel_expanded:
            # up arrow (collapse)
            arrow_path.moveTo(ar_x - ar_size, ar_y + ar_size / 2)
            arrow_path.lineTo(ar_x,             ar_y - ar_size / 2)
            arrow_path.lineTo(ar_x + ar_size,    ar_y + ar_size / 2)
        else:
            # down arrow (expand)
            arrow_path.moveTo(ar_x - ar_size, ar_y - ar_size / 2)
            arrow_path.lineTo(ar_x,             ar_y + ar_size / 2)
            arrow_path.lineTo(ar_x + ar_size,    ar_y - ar_size / 2)
        self._panel_collapse_rect = QRectF(ar_x - 10, ar_y - 10, 20, 20)
        p.setPen(QPen(qcol(prim, 200), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(arrow_path)

        # close button (×)
        cs = 16
        ccx = rect.right() - 14
        ccy = cy
        self._island_close_rect = QRectF(ccx - cs / 2, ccy - cs / 2, cs, cs)
        p.setPen(QPen(qcol(prim, 180), 1.0))
        p.setBrush(QBrush(qcol("#0a0f1c", 220)))
        p.drawEllipse(self._island_close_rect)
        s = 3.5
        p.setPen(QPen(qcol(prim, 220), 1.2))
        p.drawLine(QPointF(ccx - s, ccy - s), QPointF(ccx + s, ccy + s))
        p.drawLine(QPointF(ccx + s, ccy - s), QPointF(ccx - s, ccy + s))

        # Corner brackets (subtle)
        p.setPen(QPen(qcol(prim, 170), 1.0))
        for (bx, by, dx, dy) in [
            (rect.left() + 4,  rect.top() + 2,    1,  1),
            (rect.right() - 4, rect.top() + 2,   -1,  1),
            (rect.left() + 4,  rect.bottom() - 2,  1, -1),
            (rect.right() - 4, rect.bottom() - 2, -1, -1),
        ]:
            p.drawLine(QPointF(bx, by), QPointF(bx + 6 * dx, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + 6 * dy))

    # ── Single Card ───────────────────────────────────────────────────
    def _draw_pinned_card(self, p, c, x, y, w, h):
        """Route to the type-specific renderer."""
        # Slide-in offset for entering
        if c["anim_state"] == "entering":
            t = c["anim_t"]
            e = self._ease_out_back(t)
            slide = (1 - min(1.0, e)) * 40
            x = x + slide
            alpha = int(255 * min(1.0, e))
        elif c["anim_state"] == "leaving":
            t = c["anim_t"]
            slide = t * 40
            x = x + slide
            alpha = int(255 * (1 - t))
        else:
            alpha = 255
            # pulse: subtle scale 1.0 → 1.04 → 1.0
            if c["anim_state"] == "pulse":
                pt = c["anim_t"]
                # ease
                pulse = math.sin(pt * math.pi)
                cx, cy = x + w / 2, y + h / 2
                p.save()
                p.translate(cx, cy)
                p.scale(1.0 + 0.04 * pulse, 1.0 + 0.04 * pulse)
                p.translate(-cx, -cy)
                self._draw_card_body(p, c, x, y, w, h, alpha)
                p.restore()
                return

        self._draw_card_body(p, c, x, y, w, h, alpha)

    def _draw_card_body(self, p, c, x, y, w, h, alpha):
        mode = MODES[self._mode]
        prim = mode["primary"]; sec = mode["secondary"]; acc = mode["accent"]
        rect = QRectF(x, y, w, h)
        radius = 12

        # Card background — dark with subtle gradient
        grad = QLinearGradient(x, y, x, y + h)
        grad.setColorAt(0.0, qcol("#0e1626", int(245 * alpha / 255)))
        grad.setColorAt(1.0, qcol("#080d18", int(245 * alpha / 255)))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, QBrush(grad))

        # Left accent bar (mode color)
        accent_bar = QRectF(x + 1, y + 6, 3, h - 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(prim, int(220 * alpha / 255))))
        p.drawRoundedRect(accent_bar, 1.5, 1.5)

        # Border
        p.setPen(QPen(qcol(prim, int(100 * alpha / 255)), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Clip drawing to card body for content
        p.save()
        p.setClipPath(path)

        # Top row: icon + title + timestamp
        icon_x = x + 14
        icon_y = y + 16
        self._draw_card_icon(p, c["type"], icon_x, icon_y, prim, acc, alpha)
        p.setFont(_get_font("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol(acc, alpha)))
        p.drawText(QPointF(x + 36, y + 20), c["title"][:36])
        # timestamp
        elapsed = int(time.time() - c["pinned_at"])
        ts = f"{elapsed}s ago" if elapsed < 60 else f"{elapsed // 60}m ago"
        p.setFont(_get_font("Segoe UI", 8))
        p.setPen(QPen(qcol(prim, int(180 * alpha / 255))))
        ts_w = p.fontMetrics().horizontalAdvance(ts)
        p.drawText(QPointF(x + w - ts_w - 36, y + 20), ts)

        # Close × at top right
        cx_x = x + w - 16
        cx_y = y + 16
        cs = 7
        close_rect = QRectF(cx_x - cs, cx_y - cs, cs * 2, cs * 2)
        self._card_close_rects.append((c["id"], close_rect))
        p.setPen(QPen(qcol("#aab4c8", int(160 * alpha / 255)), 1.1))
        p.drawLine(QPointF(cx_x - 3, cx_y - 3), QPointF(cx_x + 3, cx_y + 3))
        p.drawLine(QPointF(cx_x + 3, cx_y - 3), QPointF(cx_x - 3, cx_y + 3))

        # Body — type-specific
        body_y = y + 36
        body_h = h - 42
        body_rect = QRectF(x + 14, body_y, w - 28, body_h)
        self._draw_card_content(p, c, body_rect, prim, sec, acc, alpha)

        p.restore()

    def _draw_card_icon(self, p, t, x, y, prim, acc, alpha):
        """Small icon for the card type — fits in a 16x16 box at (x,y)."""
        s = 8
        p.setPen(QPen(qcol(prim, alpha), 1.4))
        p.setBrush(QBrush(qcol(prim, int(60 * alpha / 255))))
        if t == "search" or t == "results":
            p.drawEllipse(QPointF(x, y), s - 1, s - 1)
            p.setPen(QPen(qcol(prim, alpha), 1.4))
            p.drawLine(QPointF(x + 5, y + 5), QPointF(x + 8, y + 8))
        elif t == "weather":
            # sun
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x, y), s - 1, s - 1)
            for i in range(8):
                a = i * math.pi / 4
                p.drawLine(QPointF(x + 8 * math.cos(a), y + 8 * math.sin(a)),
                           QPointF(x + 11 * math.cos(a), y + 11 * math.sin(a)))
        elif t == "music":
            # 8th note
            p.setBrush(QPen(qcol(prim, alpha), 1.4).style() == Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x - 4, y + 3), 3, 3)
            p.drawEllipse(QPointF(x + 4, y + 1), 3, 3)
            p.drawLine(QPointF(x - 1, y + 4), QPointF(x - 1, y - 6))
            p.drawLine(QPointF(x - 1, y - 6), QPointF(x + 7, y - 8))
            p.drawLine(QPointF(x + 7, y - 8), QPointF(x + 7, y - 2))
        elif t == "timer":
            p.drawEllipse(QPointF(x, y), s, s)
            p.setPen(QPen(qcol(prim, alpha), 1.2))
            p.drawLine(QPointF(x, y), QPointF(x, y - 5))
            p.drawLine(QPointF(x, y), QPointF(x + 4, y))
        elif t == "stock":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(x - 6, y + 5), QPointF(x + 6, y + 5))
            p.drawLine(QPointF(x - 6, y + 5), QPointF(x - 6, y - 1))
            p.drawLine(QPointF(x - 6, y - 1), QPointF(x - 2, y - 4))
            p.drawLine(QPointF(x - 2, y - 4), QPointF(x + 2, y + 1))
            p.drawLine(QPointF(x + 2, y + 1), QPointF(x + 6, y - 6))
        elif t == "note":
            p.drawRect(QRectF(x - 5, y - 6, 10, 12))
            for i in range(3):
                p.drawLine(QPointF(x - 3, y - 3 + i * 3), QPointF(x + 3, y - 3 + i * 3))
        elif t in ("reminder", "task"):
            p.drawRect(QRectF(x - 5, y - 5, 10, 10))
            p.drawLine(QPointF(x - 3, y), QPointF(x - 1, y + 3))
            p.drawLine(QPointF(x - 1, y + 3), QPointF(x + 4, y - 4))
        elif t == "news":
            p.drawRect(QRectF(x - 6, y - 6, 12, 12))
            p.drawLine(QPointF(x - 4, y - 3), QPointF(x + 4, y - 3))
            p.drawLine(QPointF(x - 4, y), QPointF(x + 4, y))
            p.drawLine(QPointF(x - 4, y + 3), QPointF(x + 3, y + 3))
        else:
            # generic dot
            p.drawEllipse(QPointF(x, y), s - 2, s - 2)

    def _draw_card_content(self, p, c, rect, prim, sec, acc, alpha):
        t = c["type"]
        d = c["data"]
        x = rect.left(); y = rect.top(); w = rect.width(); h = rect.height()
        if t in ("search", "results"):
            results = d.get("results", [])[:3]
            for i, r in enumerate(results):
                ry = y + i * 22
                if ry + 20 > y + h:
                    break
                p.setFont(_get_font("Segoe UI", 10, QFont.Weight.Bold))
                p.setPen(QPen(qcol(acc, alpha)))
                title = r.get("title", "")[:50]
                p.drawText(QRectF(x, ry, w, 18), Qt.AlignmentFlag.AlignVCenter, title)
                p.setFont(_get_font("Segoe UI", 8))
                p.setPen(QPen(qcol(prim, int(180 * alpha / 255))))
                url = r.get("url", "")
                if url:
                    p.drawText(QRectF(x, ry + 14, w, 12), Qt.AlignmentFlag.AlignVCenter, url[:60])
        elif t == "weather":
            city = d.get("city", "")
            temp = d.get("temp", "")
            cond = d.get("condition", "")
            hum  = d.get("humidity", "")
            p.setFont(_get_font("Segoe UI", 22, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QPointF(x, y + 28), temp)
            p.setFont(_get_font("Segoe UI", 11, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, int(220 * alpha / 255))))
            p.drawText(QPointF(x + 90, y + 14), city)
            p.setFont(_get_font("Segoe UI", 9))
            p.setPen(QPen(qcol(prim, int(200 * alpha / 255))))
            p.drawText(QPointF(x + 90, y + 30), cond + ("  ·  💧 " + hum if hum else ""))
        elif t == "music":
            title  = d.get("title", "")
            artist = d.get("artist", "")
            status = d.get("status", "playing")
            prog   = float(d.get("progress", 0))
            p.setFont(_get_font("Segoe UI", 11, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QPointF(x, y + 16), title[:30])
            p.setFont(_get_font("Segoe UI", 9))
            p.setPen(QPen(qcol(prim, int(200 * alpha / 255))))
            p.drawText(QPointF(x, y + 32), artist[:30])
            # progress bar
            bar_h = 4
            bar_rect = QRectF(x, y + 46, w - 100, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol("#1a2230", alpha)))
            p.drawRoundedRect(bar_rect, 2, 2)
            fill_rect = QRectF(bar_rect.left(), bar_rect.top(), bar_rect.width() * max(0, min(1, prog)), bar_h)
            p.setBrush(QBrush(qcol(prim, alpha)))
            p.drawRoundedRect(fill_rect, 2, 2)
            # play/pause button
            btn_x = x + w - 30
            btn_y = y + 18
            p.setBrush(QBrush(qcol(prim, alpha)))
            p.drawEllipse(QPointF(btn_x, btn_y), 10, 10)
            if status == "playing":
                p.setPen(QPen(qcol("#000", alpha), 1.6))
                p.drawLine(QPointF(btn_x - 2, btn_y - 3), QPointF(btn_x - 2, btn_y + 3))
                p.drawLine(QPointF(btn_x + 2, btn_y - 3), QPointF(btn_x + 2, btn_y + 3))
            else:
                tri = QPolygonF([QPointF(btn_x - 2, btn_y - 3),
                                 QPointF(btn_x - 2, btn_y + 3),
                                 QPointF(btn_x + 3, btn_y)])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(qcol("#000", alpha)))
                p.drawPolygon(tri)
            # track label
            p.setFont(_get_font("Segoe UI", 8))
            p.setPen(QPen(qcol(prim, int(180 * alpha / 255))))
            p.drawText(QPointF(btn_x - 14, y + 46), status.upper())
        elif t == "timer":
            label = d.get("label", "Timer")
            rem   = int(d.get("remaining_seconds", 0))
            mins  = rem // 60
            secs  = rem % 60
            p.setFont(_get_font("Segoe UI", 10, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QPointF(x, y + 14), label[:30])
            p.setFont(_get_font("Segoe UI", 22, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QPointF(x, y + 48), f"{mins:02d}:{secs:02d}")
            # control buttons (text only)
            p.setFont(_get_font("Segoe UI", 9))
            p.setPen(QPen(qcol(prim, alpha)))
            p.drawText(QPointF(x + 100, y + 38), d.get("status", "running").upper())
        elif t == "stock":
            ticker = d.get("ticker", "")
            price  = d.get("price", "")
            change = d.get("change", "")
            pct    = d.get("change_pct", "")
            up     = d.get("up", True)
            col    = "#4ade80" if up else "#f87171"
            p.setFont(_get_font("Segoe UI", 10, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QPointF(x, y + 14), ticker)
            p.setFont(_get_font("Segoe UI", 20, QFont.Weight.Bold))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QPointF(x, y + 46), price)
            p.setFont(_get_font("Segoe UI", 10, QFont.Weight.Bold))
            p.setPen(QPen(qcol(col, alpha)))
            p.drawText(QPointF(x + 130, y + 30), change)
            p.setFont(_get_font("Segoe UI", 9))
            p.drawText(QPointF(x + 130, y + 46), pct)
        elif t in ("note", "reminder", "task", "news", "quote"):
            body = d.get("body", "") or d.get("text", "") or d.get("headline", "")
            p.setFont(_get_font("Segoe UI", 10))
            p.setPen(QPen(qcol(acc, alpha)))
            # wrap manually
            words = body.split()
            line = ""
            yy = y + 16
            for word in words:
                test = (line + " " + word).strip()
                if p.fontMetrics().horizontalAdvance(test) > w:
                    p.drawText(QPointF(x, yy), line)
                    yy += 16
                    line = word
                    if yy > y + h - 16:
                        break
                else:
                    line = test
            if line and yy <= y + h - 16:
                p.drawText(QPointF(x, yy), line)
        else:
            body = d.get("body", "")
            p.setFont(_get_font("Segoe UI", 10))
            p.setPen(QPen(qcol(acc, alpha)))
            p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, str(body)[:200])


    def _state_label(self) -> str:
        return {
            "INITIALISING": "? SYSTEM BOOTING",
            "LISTENING":    "? SYSTEM ACTIVE",
            "SPEAKING":     "? SYSTEM ACTIVE",
            "THINKING":     "? SYSTEM ACTIVE",
            "MUTED":        "? SYSTEM MUTED",
        }.get(self.state, "? SYSTEM ACTIVE")

    # ───────────────────── 3D LAPTOP ─────────────────────
    def _project_3d(self, x, y, z, rot_y, rot_x, fov=520, cam_dist=620):
        cy_ = math.cos(rot_y); sy_ = math.sin(rot_y)
        x1 = x * cy_ + z * sy_
        z1 = -x * sy_ + z * cy_
        y1 = y
        cx_ = math.cos(rot_x); sx_ = math.sin(rot_x)
        y2 = y1 * cx_ - z1 * sx_
        z2 = y1 * sx_ + z1 * cx_
        denom = z2 + cam_dist
        if denom < 60: denom = 60
        persp = fov / denom
        return x1 * persp, -y2 * persp, z2

    def _draw_3d_laptop(self, p, cx, cy, scale=1.0):
        W   = 200 * scale
        D   = 140 * scale
        Hb  = 7   * scale

        # Animations — small rotation around y, with fixed forward tilt for top-down view
        rot_y = self._time_phase * 0.35 + math.sin(self._time_phase * 0.7) * 0.04
        rot_x = -0.35 + math.sin(self._time_phase * 0.55) * 0.04  # tilt forward so we see top + screen

        # ── Vertex projections (local verts from pre-computed _LAPTOP_VERTS) ──
        pts = []
        for vx, vy, vz in _LAPTOP_VERTS:
            sx_, sy_, sz_ = self._project_3d(vx, vy, vz, rot_y, rot_x)
            pts.append((cx + sx_, cy + sy_, sz_))

        # ── Face definitions: (indices, fill_color, edge_color, alpha) ──
        # Pre-computed at module scope (_LAPTOP_FACES) — no per-frame allocation
        faces = _LAPTOP_FACES

        # Sort faces by average z (back to front - draw further first)
        # Smaller z = closer to camera (after perspective)
        # After Y-rotation, points with larger z (positive) are away from camera
        # We want to draw larger z first (back), then smaller z (front)
        faces_with_z = []
        for f in faces:
            indices, fill, edge, alpha, kind = f
            avg_z = sum(pts[i][2] for i in indices) / len(indices)
            faces_with_z.append((avg_z, f))
        faces_with_z.sort(key=lambda x: -x[0])  # largest z first = back

        # Draw faces
        for _, (indices, fill, edge, alpha, kind) in faces_with_z:
            poly = QPolygonF([QPointF(pts[i][0], pts[i][1]) for i in indices])
            p.setPen(QPen(qcol(edge, alpha), 1))
            p.setBrush(QBrush(qcol(fill, alpha)))
            p.drawPolygon(poly)

        # ── Draw keyboard keys on top of base ──
        # Use the screen-space area to decide if it's worth drawing
        top_pts = [pts[i] for i in (4, 5, 6, 7)]
        top_w = max(p[0] for p in top_pts) - min(p[0] for p in top_pts)
        top_h = max(p[1] for p in top_pts) - min(p[1] for p in top_pts)
        # Always draw if polygon is large enough; edge-on = small = skipped
        if top_w > 30 and top_h > 20:
            self._draw_laptop_keyboard(p, top_pts, scale)

        # ── Draw terminal on screen ──
        scr_pts = [pts[i] for i in (8, 9, 10, 11)]
        scr_w = max(p[0] for p in scr_pts) - min(p[0] for p in scr_pts)
        scr_h = max(p[1] for p in scr_pts) - min(p[1] for p in scr_pts)
        if scr_w > 25 and scr_h > 20:
            self._draw_laptop_screen(p, scr_pts, scale)

        # ── AEGIS glow underneath ──
        glow_r = max(W, D) * 1.3
        glow = QRadialGradient(QPointF(cx, cy + Hb * 1.2), glow_r)
        glow.setColorAt(0.0, qcol(C.ACCENT, 40))
        glow.setColorAt(0.5, qcol(C.ACCENT, 18))
        glow.setColorAt(1.0, qcol(C.ACCENT, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy + Hb * 1.2), glow_r, glow_r * 0.4)

    def _draw_laptop_keyboard(self, p, top_pts, scale):
        # Project the 4 corners of the top face to get a 2D quadrilateral
        # Draw a grid of small keys on this surface (use pre-computed _LAPTOP_KEYS)
        # OPTIMIZED: build ONE QPainterPath for all 60 keys (vs 60 drawPolygon calls).
        key_path = QPainterPath()
        space_path = QPainterPath()
        for u0, v0, u1, v1, is_space in _LAPTOP_KEYS:
            a = _bilinear(top_pts, u0, v0)
            b = _bilinear(top_pts, u1, v0)
            c = _bilinear(top_pts, u1, v1)
            d = _bilinear(top_pts, u0, v1)
            sub = QPainterPath()
            sub.moveTo(a[0], a[1])
            sub.lineTo(b[0], b[1])
            sub.lineTo(c[0], c[1])
            sub.lineTo(d[0], d[1])
            sub.closeSubpath()
            if is_space:
                space_path.addPath(sub)
            else:
                key_path.addPath(sub)
        p.setPen(_get_pen("#1a3040", 200, 0.6))
        p.setBrush(_get_brush("#3a5870", 220))
        p.drawPath(key_path)
        p.setBrush(_get_brush("#4a7090", 220))
        p.drawPath(space_path)
        # Trackpad area at front
        u0, u1 = 0.30, 0.70
        v0, v1 = 0.02, 0.14
        a = _bilinear(top_pts, u0, v0)
        b = _bilinear(top_pts, u1, v0)
        c = _bilinear(top_pts, u1, v1)
        d = _bilinear(top_pts, u0, v1)
        tp = QPainterPath()
        tp.moveTo(a[0], a[1])
        tp.lineTo(b[0], b[1])
        tp.lineTo(c[0], c[1])
        tp.lineTo(d[0], d[1])
        tp.closeSubpath()
        p.setPen(_get_pen("#5a8aa8", 200, 1))
        p.setBrush(_get_brush("#1a3548", 180))
        p.drawPath(tp)

    def _draw_laptop_screen(self, p, scr_pts, scale):
        # 4 corners of the screen face
        p1, p2, p3, p4 = scr_pts
        xs = [pt[0] for pt in scr_pts]
        ys = [pt[1] for pt in scr_pts]
        sw = max(xs) - min(xs)
        sh = max(ys) - min(ys)
        if sw < 20 or sh < 20:
            return
        # Screen face polygon — clean dark panel, no text overlay
        bg = QPolygonF([QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]),
                        QPointF(p3[0], p3[1]), QPointF(p4[0], p4[1])])
        p.setPen(QPen(qcol(C.ACCENT, 180), 1))
        p.setBrush(QBrush(qcol("#01080c", 250)))
        p.drawPolygon(bg)

    # ───────────────────── BATTLE COMPASS ─────────────────────
    def _draw_battle_compass(self, p, cx, cy, R):
        # Multiple concentric rotating rings, plasma reactor at center
        rot1 = self._time_phase * 0.6   # outer ring rotates clockwise
        rot2 = -self._time_phase * 0.9  # inner ring rotates counter-clockwise
        rot3 = self._time_phase * 1.8   # tick marks rotate

        # Outer glow
        halo = QRadialGradient(QPointF(cx, cy), R * 1.4)
        halo.setColorAt(0.0, qcol(self._r_color[0], int(40 + 30 * self._reactor_pulse)))
        halo.setColorAt(0.6, qcol(self._r_color[0], 18))
        halo.setColorAt(1.0, qcol(self._r_color[0], 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), R * 1.4, R * 1.4)

        # Outer ring (rotating clockwise) - big tick marks — OPTIMIZED cached pens
        n_outer = 36
        pen_major = _get_pen(C.AMBER, 220, 2.0)
        pen_minor = _get_pen(C.TEXT_DIM, 130, 0.8)
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(rot1))
        for i in range(n_outer):
            ang = (i / n_outer) * math.tau
            major = (i % 9 == 0)
            r1 = R * 0.92
            r2 = R * (0.74 if major else 0.82)
            p.setPen(pen_major if major else pen_minor)
            p.drawLine(QPointF(r1 * math.cos(ang), r1 * math.sin(ang)),
                       QPointF(r2 * math.cos(ang), r2 * math.sin(ang)))
        # Cardinal direction labels
        p.rotate(-math.degrees(rot1))  # un-rotate so labels stay upright
        p.setFont(_get_font("Courier New", 9, 1))
        pen_label = _get_pen(C.ACCENT_BR, 240, 1)
        for label, ang in (("N", -math.pi/2), ("E", 0),
                            ("S", math.pi/2), ("W", math.pi)):
            lx = (R * 0.62) * math.cos(ang)
            ly = (R * 0.62) * math.sin(ang)
            p.setPen(pen_label)
            p.drawText(QRectF(lx - 12, ly - 7, 24, 14),
                       Qt.AlignmentFlag.AlignCenter, label)
        p.restore()

        # Middle ring (rotating counter-clockwise) - degree numbers
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(rot2))
        n_mid = 12
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        for i in range(n_mid):
            ang = (i / n_mid) * math.tau - math.pi / 2
            r1 = R * 0.70
            r2 = R * 0.55
            p.setPen(QPen(qcol(C.VIOLET, 200), 1.2))
            p.drawLine(QPointF(r1 * math.cos(ang), r1 * math.sin(ang)),
                       QPointF(r2 * math.cos(ang), r2 * math.sin(ang)))
            # number
            num = str(int(i * (360 / n_mid)))
            tx = (R * 0.46) * math.cos(ang) - 12
            ty = (R * 0.46) * math.sin(ang) - 6
            p.setPen(QPen(qcol(C.VIOLET, 200), 1))
            p.drawText(QRectF(tx, ty, 24, 12),
                       Qt.AlignmentFlag.AlignCenter, num)
        p.restore()

        # Rotating target reticle (in the ring area)
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(rot3 * 0.4))
        for ang_off in (0, math.pi/2, math.pi/4, 3*math.pi/4):
            a1 = ang_off
            a2 = a1 + math.pi/8
            p.setPen(QPen(qcol(C.GOLD, 200), 1.4))
            p.drawArc(QRectF(-R * 0.78, -R * 0.78, R * 1.56, R * 1.56),
                      int(math.degrees(a1) * 16), int(math.degrees(a2 - a1) * 16))
        p.restore()

        # FLIGHT label at top
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.setPen(QPen(qcol(self._r_color[1], 240), 1))
        p.drawText(QRectF(cx - 60, cy - R * 0.95, 120, 18),
                   Qt.AlignmentFlag.AlignCenter, "FLIGHT")
        # Rotating needle pointing inward
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(self._time_phase * 0.4))
        needle_pulse = 0.7 + 0.3 * math.sin(self._time_phase * 3.0)
        p.setPen(QPen(qcol(self._r_color[0], int(220 * needle_pulse)), 1.6))
        p.drawLine(QPointF(0, 0), QPointF(0, -R * 0.85))
        # needle tip
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(self._r_color[1], int(230 * needle_pulse))))
        p.drawEllipse(QPointF(0, -R * 0.85), 4, 4)
        p.restore()

        # Inner: plasma reactor (smaller version, voice-reactive)
        inner_R = R * 0.45
        self._draw_plasma_reactor(p, cx, cy, inner_R)

        # Central core dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol("#ffffff", int(180 * self._reactor_pulse))))
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        # "BATTLE" label below center
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT_BR, 220), 1))
        p.drawText(QRectF(cx - 40, cy + inner_R * 0.30, 80, 12),
                   Qt.AlignmentFlag.AlignCenter, "CORE.LIVE")

    def _draw_data_flow(self, p, x1, y1, x2, y2):
        # Animated data flow lines (dotted curves with moving particles)
        n_lines = 4
        for li in range(n_lines):
            off = li * 18
            path = QPainterPath()
            midx = (x1 + x2) / 2
            midy = min(y1, y2) - 30 - off
            path.moveTo(x1, y1 - off)
            path.quadTo(midx, midy, x2, y2 - off)
            col = (C.ACCENT, C.AMBER, C.VIOLET, C.ROSE)[li]
            # Dashed path
            pen = QPen(qcol(col, 80), 1, Qt.PenStyle.DashLine)
            pen.setDashPattern([3, 5])
            pen.setDashOffset(-self._tick * 0.4 + li * 4)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            # Moving particle along the path
            t = (self._tick * 0.012 + li * 0.27) % 1.0
            pt = path.pointAtPercent(t)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(col, 220)))
            p.drawEllipse(pt, 2.5, 2.5)
            # small glow
            glow_grad = QRadialGradient(pt, 8)
            glow_grad.setColorAt(0.0, qcol(col, 120))
            glow_grad.setColorAt(1.0, qcol(col, 0))
            p.setBrush(QBrush(glow_grad))
            p.drawEllipse(pt, 8, 8)

    def _draw_quick_stats(self, p, x, y, w):
        # 4 small stats in a row at top of compass area
        items = [
            ("PWR",  f"{max(0, 100 - self._cpu_pct*0.5):3.0f}", C.SUCCESS),
            ("SPD",  f"{min(99, 60 + self._audio_level*30):3.0f}", C.ACCENT),
            ("TGT",  f"{min(99, 75 + math.sin(self._time_phase)*15):3.0f}", C.GOLD),
            ("LCK",  "100", C.AMBER),
        ]
        cw = w / len(items)
        for i, (lab, val, col) in enumerate(items):
            cx = x + i * cw + cw / 2
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
            p.drawText(QRectF(cx - 25, y, 50, 11),
                       Qt.AlignmentFlag.AlignCenter, lab)
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(col, 230), 1))
            p.drawText(QRectF(cx - 25, y + 11, 50, 14),
                       Qt.AlignmentFlag.AlignCenter, val)


    def _status_card(self, p, x, y, w, h, title, sub, icon, color, on):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 10, 10)
        p.setPen(QPen(qcol(color, 200), 1))
        p.setBrush(QBrush(qcol(C.PANEL_HI, 140)))
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(color, 220)))
        p.fillRect(QRectF(x + 1, y + 8, 3, h - 16), qcol(color, 220))
        self._card_icon(p, x + 18, y + h / 2, icon, color)
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT, 230), 1))
        p.drawText(QRectF(x + 44, y + 12, w - 90, 14),
                   Qt.AlignmentFlag.AlignLeft, title)
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(x + 44, y + 28, w - 90, 12),
                   Qt.AlignmentFlag.AlignLeft, sub)
        dot_x = x + w - 18
        dot_y = y + h / 2
        pulse = 0.6 + 0.4 * math.sin(self._tick * 0.15)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(color, int(240 * pulse))))
            p.drawEllipse(QPointF(dot_x, dot_y), 4, 4)
            for k in range(2):
                t = (self._tick * 0.03 + k * 0.5) % 1.0
                pr = 4 + t * 10
                pa = int(160 * (1 - t))
                p.setPen(QPen(qcol(color, pa), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(dot_x, dot_y), pr, pr)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.TEXT_MUTED, 180)))
            p.drawEllipse(QPointF(dot_x, dot_y), 4, 4)

    def _card_icon(self, p, cx, cy, kind, color):
        p.setPen(QPen(qcol(color, 220), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "files":
            p.drawRect(QRectF(cx - 7, cy - 5, 14, 10))
            p.drawLine(QPointF(cx - 7, cy - 1), QPointF(cx + 7, cy - 1))
        elif kind == "memory":
            p.drawRect(QRectF(cx - 7, cy - 5, 14, 10))
            for i in range(4):
                px = cx - 5 + i * 3
                p.drawLine(QPointF(px, cy - 3), QPointF(px, cy + 3))
        elif kind == "history":
            p.drawEllipse(QPointF(cx, cy), 7, 7)
            p.setPen(QPen(qcol(color, 220), 1.2))
            p.drawLine(QPointF(cx, cy), QPointF(cx + 4, cy - 2))
        elif kind == "user":
            p.drawEllipse(QPointF(cx, cy - 2), 4, 4)
            p.drawArc(QRectF(cx - 6, cy + 1, 12, 8), 180 * 16, 180 * 16)

    def _draw_connection(self, p, x1, y1, x2, y2, color):
        path = QPainterPath()
        path.moveTo(x1, y1)
        cx_ctl = (x1 + x2) / 2
        cy_ctl = min(y1, y2) - 20
        path.quadTo(cx_ctl, cy_ctl, x2, y2)
        pen_glow = QPen(qcol(color, 50), 4, Qt.PenStyle.DashLine)
        pen_glow.setDashPattern([4, 4])
        pen_glow.setDashOffset(-self._tick * 0.3)
        p.setPen(pen_glow)
        p.drawPath(path)
        pen_main = QPen(qcol(color, 180), 1.2, Qt.PenStyle.DashLine)
        pen_main.setDashPattern([4, 4])
        pen_main.setDashOffset(-self._tick * 0.3)
        p.setPen(pen_main)
        p.drawPath(path)
        t = (self._tick * 0.008) % 1.0
        bx = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx_ctl + t ** 2 * x2
        by = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy_ctl + t ** 2 * y2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(color, 240)))
        p.drawEllipse(QPointF(bx, by), 3, 3)


    def _draw_sphere_cluster(self, p, cx, cy, R):
        ring_c, mid_c, bright_c, _ = self._r_color
        intensity = self._r_intensity
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * 2)
        perspective = 600

        # Outer glow halo
        halo_r = R * 1.4
        halo = QRadialGradient(QPointF(cx, cy), halo_r)
        halo.setColorAt(0.0, qcol(ring_c, int(60 * intensity)))
        halo.setColorAt(0.5, qcol(ring_c, int(20 * intensity)))
        halo.setColorAt(1.0, qcol(ring_c, 0))
        p.setBrush(QBrush(halo))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        # 3 orbital rings
        for i, (off, w) in enumerate([(0, 1.3), (60, 1.1), (120, 0.9)]):
            p.save()
            p.translate(cx, cy)
            p.rotate(self._sphere_angle_y * 30 + off)
            rx = R * w
            ry = R * 0.3
            p.setPen(QPen(qcol(ring_c, 50), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), rx, ry)
            p.restore()

        # Sphere particles (3D-projected) — OPTIMIZED: group by color bucket
        # so we use ONE brush per bucket instead of one per particle.
        ang_y = self._sphere_angle_y
        ang_x = self._sphere_angle_x
        cos_y, sin_y = math.cos(ang_y), math.sin(ang_y)
        cos_x, sin_x = math.cos(ang_x), math.sin(ang_x)
        projected = []
        for part in self._sphere_particles:
            x1 = part["x"] * cos_y - part["z"] * sin_y
            z1 = part["x"] * sin_y + part["z"] * cos_y
            y1 = part["y"] * cos_x - z1 * sin_x
            z2 = part["y"] * sin_x + z1 * cos_x
            f = perspective / (perspective + z2 * R)
            px = cx + x1 * R * f
            py = cy + y1 * R * f
            front_factor = (z2 + 1) / 2
            projected.append((px, py, front_factor, f, part))
        projected.sort(key=lambda item: item[2])
        # Group by color bucket
        bright_pts, mid_pts, ring_pts = [], [], []
        bright_glow, mid_glow = [], []
        for px, py, front, f, part in projected:
            tw = 0.6 + 0.4 * math.sin(self._time_phase * 2 + part["phase"])
            size = part["size"] * (0.5 + 0.6 * f)
            if front > 0.6:
                bright_pts.append((px, py, size))
                if front > 0.75:
                    bright_glow.append((px, py, size))
            elif front > 0.3:
                mid_pts.append((px, py, size))
                if front > 0.75:
                    mid_glow.append((px, py, size))
            else:
                ring_pts.append((px, py, size))
        p.setPen(Qt.PenStyle.NoPen)
        for color, items in ((bright_c, bright_pts), (mid_c, mid_pts), (ring_c, ring_pts)):
            if not items:
                continue
            p.setBrush(_get_brush(color, 220))
            for px, py, size in items:
                p.drawEllipse(QPointF(px, py), size, size)
        # Glows (only on highly-front particles) — alpha bucket 110
        for color, items in ((bright_c, bright_glow), (mid_c, mid_glow)):
            if not items:
                continue
            p.setBrush(_get_brush(color, 110))
            for px, py, size in items:
                p.drawEllipse(QPointF(px, py), size * 3, size * 3)

        # Center bright core
        core_r = 6 + 2 * pulse
        core_grad = QRadialGradient(QPointF(cx, cy), core_r * 2)
        core_grad.setColorAt(0.0, qcol("#ffffff", 255))
        core_grad.setColorAt(0.5, qcol(bright_c, 200))
        core_grad.setColorAt(1.0, qcol(ring_c, 0))
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(cx, cy), core_r * 2, core_r * 2)

        # Outer sphere boundary
        p.setPen(QPen(qcol(ring_c, 80), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R, R)

    def _terminate_button(self, p, cx, cy):
        w, h = 130, 32
        x = cx - w / 2
        y = cy - h / 2
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        glow = QRadialGradient(QPointF(cx, cy), w * 0.7)
        glow.setColorAt(0.0, qcol(C.DANGER, 60))
        glow.setColorAt(1.0, qcol(C.DANGER, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), w * 0.7, h * 1.5)
        p.setBrush(QBrush(qcol(C.DANGER, 230)))
        p.drawPath(path)
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol("#ffffff", 255), 1))
        p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, "TERMINATE")

    # ----- WORLD MAP (replaces old NEURAL CORE) -----
    def _rebuild_world_cache(self, mx, my, mw, mh):
        """Build static geometry for the world map (called once per resize)."""
        # Continents: pre-project vertices, compute centroids & max-radii
        self._wmap_continents = []
        for cont in _WORLD_CONTINENTS:
            pts = []
            for lat, lon in cont:
                px = mx + (lon + 180) / 360.0 * mw
                py = my + (90 - lat) / 180.0 * mh
                pts.append((px, py))
            cx_c = sum(p[0] for p in pts) / len(pts)
            cy_c = sum(p[1] for p in pts) / len(pts)
            max_r = max(math.hypot(p[0] - cx_c, p[1] - cy_c) for p in pts) or 1
            poly = QPolygonF([QPointF(p[0], p[1]) for p in pts])
            self._wmap_continents.append((cx_c, cy_c, max_r, poly, pts))
        # City nodes (positions + labels)
        self._wmap_nodes = []
        for lat, lon, label in _WORLD_NODES:
            px = mx + (lon + 180) / 360.0 * mw
            py = my + (90 - lat) / 180.0 * mh
            self._wmap_nodes.append((px, py, label))
        # Data links (start, end, and a reusable QPainterPath)
        self._wmap_links = []
        for (lat1, lon1), (lat2, lon2) in _WORLD_LINKS:
            x1 = mx + (lon1 + 180) / 360.0 * mw
            y1 = my + (90 - lat1) / 180.0 * mh
            x2 = mx + (lon2 + 180) / 360.0 * mw
            y2 = my + (90 - lat2) / 180.0 * mh
            midx = (x1 + x2) / 2
            midy = (y1 + y2) / 2 - 22
            path = QPainterPath()
            path.moveTo(x1, y1)
            path.quadTo(midx, midy, x2, y2)
            self._wmap_links.append((x1, y1, x2, y2, path))
        # Threat zones (centers + radius + severity)
        self._wmap_threats = []
        for tlat, tlon, trad, tsev in _WORLD_THREATS:
            tcx = mx + (tlon + 180) / 360.0 * mw
            tcy = my + (90 - tlat) / 180.0 * mh
            tr = max(trad * mw / 360.0, trad * mh / 180.0)
            self._wmap_threats.append((tcx, tcy, tr, tsev))
        # Star field (60 deterministic stars, smaller and fewer than before)
        import random as _r
        rng = _r.Random(42)
        self._wmap_stars = []
        for _ in range(60):
            sx = mx + rng.random() * mw
            sy = my + rng.random() * mh
            sz = rng.choice([0.6, 0.8, 1.0, 1.2, 1.4])
            phase = rng.uniform(0, math.tau)
            self._wmap_stars.append((sx, sy, sz, phase))
        # Grid reference lines (equator, tropics, greenwich)
        self._wmap_eq_y = my + mh / 2
        self._wmap_greenwich_x = mx + 180 / 360.0 * mw
        self._wmap_cache_key = (mx, my, mw, mh)

    def _draw_command_center(self, p, x, y, w, h):
        """Holographic tactical world map (optimized: static geometry cached)."""
        flicker = 1.0 + 0.04 * math.sin(self._tick * 0.45) + 0.02 * math.sin(self._tick * 1.7)
        flicker = max(0.85, min(1.05, flicker))

        # Panel frame
        self._panel(p, x + 14, y + 14, w - 28, h - 28, radius=14)
        self._draw_corner_brackets(p, QRectF(x + 20, y + 18, w - 40, h - 36), 14, C.ACCENT, 200)

        # Header
        p.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT, 230), 1))
        p.drawText(QRectF(x + 30, y + 30, 300, 20),
                   Qt.AlignmentFlag.AlignLeft, "GLOBAL NET")
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(x + 30, y + 46, 300, 10),
                   Qt.AlignmentFlag.AlignLeft, "//  TACTICAL OVERVIEW  //  STEREO  3D  //  PROJ EQUIRECT")
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(x + 30, y + 30, w - 60, 16),
                   Qt.AlignmentFlag.AlignRight,
                   "UTC  " + datetime.utcnow().strftime("%H:%M:%S") + "   //   "
                   + datetime.now().strftime("%A  %d %b %Y"))

        # Status dot
        sd_x, sd_y = x + 140, y + 40
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * 3.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.SUCCESS if self.state != "MUTED" else C.WARNING,
                               int(180 + 60 * pulse))))
        p.drawEllipse(QPointF(sd_x, sd_y), 3, 3)
        for k in range(2):
            t = (self._tick * 0.025 + k * 0.5) % 1.0
            pr = 3 + t * 12
            pa = int(180 * (1 - t))
            p.setPen(QPen(qcol(C.ACCENT, pa), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(sd_x, sd_y), pr, pr)

        # Map area
        mx = x + 50
        my = y + 70
        mw = w - 100
        mh = h - 130

        # Rebuild cache if dimensions changed
        if self._wmap_cache_key != (mx, my, mw, mh):
            self._rebuild_world_cache(mx, my, mw, mh)

        # Apply flicker via color alpha (cheap) instead of setOpacity (expensive).
        # Flicker varies between 0.85-1.05; we scale the background alpha accordingly.
        bg_a = int(220 * flicker)

        # Background gradient
        bg = QLinearGradient(0, my, 0, my + mh)
        bg.setColorAt(0.0, qcol("#02080c", bg_a))
        bg.setColorAt(0.5, qcol("#03101a", bg_a))
        bg.setColorAt(1.0, qcol("#02080c", bg_a))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRect(QRectF(mx, my, mw, mh))

        # Lat/lon grid (15° intervals, cached pen)
        grid_pen_thin = QPen(qcol(C.ACCENT, 22), 0.5)
        grid_pen_bold = QPen(qcol(C.ACCENT, 50), 0.5)
        for lon in range(-180, 181, 15):
            gx = mx + (lon + 180) / 360.0 * mw
            p.setPen(grid_pen_bold if lon % 30 == 0 else grid_pen_thin)
            p.drawLine(QPointF(gx, my), QPointF(gx, my + mh))
        for lat in range(-60, 91, 15):
            gy = my + (90 - lat) / 180.0 * mh
            p.setPen(grid_pen_bold if lat % 30 == 0 else grid_pen_thin)
            p.drawLine(QPointF(mx, gy), QPointF(mx + mw, gy))
        # Equator + Tropics emphasized
        for lat_eq in (0, 23, -23):
            gy = my + (90 - lat_eq) / 180.0 * mh
            p.setPen(QPen(qcol(C.ACCENT, 90 if lat_eq == 0 else 50), 0.8))
            p.drawLine(QPointF(mx, gy), QPointF(mx + mw, gy))
        # Greenwich meridian
        p.setPen(QPen(qcol(C.ACCENT, 70), 0.8))
        p.drawLine(QPointF(self._wmap_greenwich_x, my),
                   QPointF(self._wmap_greenwich_x, my + mh))

        # Star field (60 stars, deterministic positions, twinkle by phase)
        p.setPen(Qt.PenStyle.NoPen)
        # 3 alpha-bucket shared brushes (low/mid/high) — reused across 60 stars.
        star_lo, star_md, star_hi = _get_brush(C.ACCENT, 60), _get_brush(C.ACCENT, 130), _get_brush(C.ACCENT, 200)
        for sx, sy, sz, phase in self._wmap_stars:
            tw = 0.4 + 0.6 * abs(math.sin(self._tick * 0.3 + phase))
            p.setBrush(star_hi if tw > 0.7 else (star_md if tw > 0.4 else star_lo))
            p.drawEllipse(QPointF(sx, sy), sz, sz)

        # Clip to map area — wrap in save/restore so crosshair below is unclipped.
        p.save()
        p.setClipRect(QRectF(mx, my, mw, mh))

        # Continents (cached polygons + pre-computed centroids/radii)
        for cx_c, cy_c, max_r, poly, pts in self._wmap_continents:
            grad = QRadialGradient(QPointF(cx_c, cy_c), max_r * 1.4)
            grad.setColorAt(0.0, qcol(C.ACCENT, 80))
            grad.setColorAt(0.4, qcol(C.ACCENT, 45))
            grad.setColorAt(1.0, qcol(C.ACCENT, 18))
            p.setPen(QPen(qcol(C.ACCENT, 130), 1.0))
            p.setBrush(QBrush(grad))
            p.drawPolygon(poly)
            # Outline
            p.setPen(QPen(qcol(C.ACCENT, 160), 0.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(poly)
            # Vertex nodes — single solid dot per vertex (faster than radial gradient)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.ACCENT, 200)))
            for px, py in pts:
                p.drawEllipse(QPointF(px, py), 1.6, 1.6)

        # Threat zones
        for tcx, tcy, tr, tsev in self._wmap_threats:
            threat_pulse = 0.5 + 0.5 * math.sin(self._time_phase * (2.0 + tsev * 0.5))
            p.setPen(QPen(qcol(C.DANGER, int(60 + 80 * threat_pulse)), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(tcx, tcy), tr + 2 + threat_pulse * 4, tr + 2 + threat_pulse * 4)
            p.setPen(QPen(qcol(C.DANGER, 200), 1))
            p.drawEllipse(QPointF(tcx, tcy), tr, tr)
            p.setPen(QPen(qcol(C.DANGER, 220), 1.2))
            p.drawLine(QPointF(tcx - 4, tcy), QPointF(tcx + 4, tcy))
            p.drawLine(QPointF(tcx, tcy - 4), QPointF(tcx, tcy + 4))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.DANGER, 230)))
            for k in range(tsev):
                p.drawRect(QRectF(tcx + tr + 4, tcy - 4 + k * 3, 2, 2))

        # Data-flow lines (cached paths, just update dash-offset for animation)
        for li, (x1, y1, x2, y2, path) in enumerate(self._wmap_links):
            pen = QPen(qcol(C.ACCENT, 80), 0.8, Qt.PenStyle.DashLine)
            pen.setDashPattern([2, 4])
            pen.setDashOffset(-self._tick * 0.5 + li * 3)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            # Animated particle + 2-dot trail (reduced from 4)
            t = (self._tick * 0.010 + li * 0.18) % 1.0
            pt = path.pointAtPercent(t)
            for ti in range(2):
                tb = (t - ti * 0.018) % 1.0
                ptt = path.pointAtPercent(tb)
                p.setBrush(QBrush(qcol(C.ACCENT, int(180 * (1 - ti / 2.0) * 0.6))))
                rad = 2.6 - ti * 0.5
                p.drawEllipse(ptt, rad, rad)
            gr = QRadialGradient(pt, 8)
            gr.setColorAt(0.0, qcol(C.ACCENT, 230))
            gr.setColorAt(0.4, qcol(C.ACCENT, 100))
            gr.setColorAt(1.0, qcol(C.ACCENT, 0))
            p.setBrush(QBrush(gr))
            p.drawEllipse(pt, 8, 8)
            p.setBrush(QBrush(qcol("#ffffff", 255)))
            p.drawEllipse(pt, 1.8, 1.8)

        # City nodes (no per-node setPen for static parts)
        p.setPen(Qt.PenStyle.NoPen)
        for ni, (px, py, _label) in enumerate(self._wmap_nodes):
            importance = 1 if ni % 5 == 0 else 2
            col = C.ACCENT if importance == 1 else C.ACCENT_BR
            # ring (outlined)
            pulse2 = 0.5 + 0.5 * math.sin(self._time_phase * 2.2
                                          + self._wmap_nodes[ni][0] * 0.001
                                          + self._wmap_nodes[ni][1] * 0.001)
            ring_r = (3 if importance == 1 else 2.5) + pulse2 * (2 if importance == 1 else 1.2)
            p.setPen(QPen(qcol(col, int(180 + 60 * pulse2)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px, py), ring_r, ring_r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(col, 250)))
            p.drawEllipse(QPointF(px, py), 1.8 if importance == 1 else 1.4,
                          1.8 if importance == 1 else 1.4)

        # Selected / targeted city (rotating lock-on)
        sel_idx = int(self._time_phase * 0.18) % len(self._wmap_nodes)
        sel_x, sel_y, sel_label = self._wmap_nodes[sel_idx]
        # Outer rotating dashed ring
        p.save()
        p.translate(sel_x, sel_y)
        p.rotate(math.degrees(self._time_phase * 2.0))
        ppen = QPen(qcol(C.GOLD, 220), 1.2, Qt.PenStyle.DashLine)
        ppen.setDashPattern([4, 3])
        ppen.setDashOffset(-self._tick * 0.3)
        p.setPen(ppen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 14, 14)
        p.restore()
        # Inner solid ring
        p.setPen(QPen(qcol(C.GOLD, 230), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(sel_x, sel_y), 9, 9)
        # 4 corner brackets (cached pen)
        bp = QPen(qcol(C.GOLD, 240), 1.4)
        p.setPen(bp)
        p.drawLine(QPointF(sel_x - 16, sel_y - 11), QPointF(sel_x - 16, sel_y - 16))
        p.drawLine(QPointF(sel_x - 16, sel_y - 16), QPointF(sel_x - 11, sel_y - 16))
        p.drawLine(QPointF(sel_x + 16, sel_y - 11), QPointF(sel_x + 16, sel_y - 16))
        p.drawLine(QPointF(sel_x + 16, sel_y - 16), QPointF(sel_x + 11, sel_y - 16))
        p.drawLine(QPointF(sel_x - 16, sel_y + 11), QPointF(sel_x - 16, sel_y + 16))
        p.drawLine(QPointF(sel_x - 16, sel_y + 16), QPointF(sel_x - 11, sel_y + 16))
        p.drawLine(QPointF(sel_x + 16, sel_y + 11), QPointF(sel_x + 16, sel_y + 16))
        p.drawLine(QPointF(sel_x + 16, sel_y + 16), QPointF(sel_x + 11, sel_y + 16))
        # Center dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.GOLD, 255)))
        p.drawEllipse(QPointF(sel_x, sel_y), 2.0, 2.0)

        # Scanning sweep (horizontal band)
        scan_t = (self._time_phase * 0.12) % 1.0
        scan_y = my + scan_t * mh
        band = QLinearGradient(0, scan_y - 22, 0, scan_y + 22)
        band.setColorAt(0.0, qcol(C.ACCENT, 0))
        band.setColorAt(0.5, qcol(C.ACCENT, 55))
        band.setColorAt(1.0, qcol(C.ACCENT, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(band))
        p.drawRect(QRectF(mx, scan_y - 22, mw, 44))
        p.setPen(QPen(qcol(C.ACCENT, 200), 1.0))
        p.drawLine(QPointF(mx, scan_y), QPointF(mx + mw, scan_y))
        p.setPen(QPen(qcol("#ffffff", 220), 1.4))
        p.drawLine(QPointF(mx, scan_y), QPointF(mx + 60, scan_y))

        # Concentric scanning rings from center
        sc_cx = mx + mw / 2
        sc_cy = my + mh / 2
        max_r_outer = max(mw, mh) * 0.6
        for ring in range(3):
            rt = (self._tick * 0.008 + ring * 0.33) % 1.0
            rr = 10 + rt * max_r_outer
            ra = int(160 * (1 - rt))
            if ra < 5:
                continue
            p.setPen(QPen(qcol(C.ACCENT, ra), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(sc_cx, sc_cy), rr, rr * 0.55)

        p.restore()  # end flicker + clip

        # Crosshair (center)
        cx_c, cy_c = mx + mw / 2, my + mh / 2
        p.setPen(QPen(qcol(C.ACCENT, 200), 1.0))
        p.drawLine(QPointF(cx_c - 12, cy_c), QPointF(cx_c + 12, cy_c))
        p.drawLine(QPointF(cx_c, cy_c - 12), QPointF(cx_c, cy_c + 12))
        p.setPen(QPen(qcol(C.ACCENT, 100), 0.8))
        p.drawEllipse(QPointF(cx_c, cy_c), 8, 8)
        p.setPen(QPen(qcol(C.ACCENT, 200), 0.6))
        p.drawEllipse(QPointF(cx_c, cy_c), 16, 16)
        # 4 tick marks
        for ang in (0, 90, 180, 270):
            ar = math.radians(ang)
            p.setPen(QPen(qcol(C.ACCENT, 200), 1))
            p.drawLine(QPointF(cx_c + 18 * math.cos(ar), cy_c + 18 * math.sin(ar)),
                       QPointF(cx_c + 22 * math.cos(ar), cy_c + 22 * math.sin(ar)))

        # Compass rose (top-right of map)
        cr_cx = mx + mw - 26
        cr_cy = my + 26
        cr_r = 16
        p.setPen(QPen(qcol(C.ACCENT_BR, 180), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cr_cx, cr_cy), cr_r, cr_r)
        p.save()
        p.translate(cr_cx, cr_cy)
        p.rotate(math.degrees(self._time_phase * 0.4))
        cp = QPen(qcol(C.ACCENT, 220), 1)
        p.setPen(cp)
        for ang in (0, 90, 180, 270):
            ar = math.radians(ang)
            p.drawLine(QPointF((cr_r - 4) * math.cos(ar), (cr_r - 4) * math.sin(ar)),
                       QPointF((cr_r - 1) * math.cos(ar), (cr_r - 1) * math.sin(ar)))
        p.restore()
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT_BR, 220), 0.8))
        p.drawText(QRectF(cr_cx - 6, cr_cy - cr_r - 8, 12, 8), Qt.AlignmentFlag.AlignCenter, "N")
        p.drawText(QRectF(cr_cx - 6, cr_cy + cr_r + 1, 12, 8), Qt.AlignmentFlag.AlignCenter, "S")
        p.drawText(QRectF(cr_cx - cr_r - 8, cr_cy - 4, 12, 8), Qt.AlignmentFlag.AlignCenter, "W")
        p.drawText(QRectF(cr_cx + cr_r - 4, cr_cy - 4, 12, 8), Qt.AlignmentFlag.AlignCenter, "E")

        # Scale bar
        sb_x, sb_y, sb_w = mx + 12, my + mh - 12, 50
        p.setPen(QPen(qcol(C.ACCENT_BR, 200), 1))
        p.drawLine(QPointF(sb_x, sb_y), QPointF(sb_x + sb_w, sb_y))
        p.drawLine(QPointF(sb_x, sb_y - 3), QPointF(sb_x, sb_y + 3))
        p.drawLine(QPointF(sb_x + sb_w, sb_y - 3), QPointF(sb_x + sb_w, sb_y + 3))
        p.setFont(QFont("Courier New", 5, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT_BR, 200), 0.8))
        p.drawText(QPointF(sb_x, sb_y - 5), "0")
        p.drawText(QPointF(sb_x + sb_w - 10, sb_y - 5), "5000km")

        # City labels (key ones)
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        lp = QPen(qcol(C.ACCENT_BR, 170), 0.7)
        p.setPen(lp)
        for px, py, label in self._wmap_nodes[:10]:
            if abs(px - sel_x) < 30 and abs(py - sel_y) < 14:
                continue
            p.drawText(QPointF(px + 5, py - 3), label)

        # TGT LOCK card
        card_x, card_y, card_w, card_h = mx + 8, my + 6, 130, 38
        p.setPen(QPen(qcol(C.GOLD, 180), 0.8))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
        p.drawRect(QRectF(card_x, card_y, card_w, card_h))
        p.setPen(QPen(qcol(C.GOLD, 200), 0.8))
        p.drawLine(QPointF(card_x, card_y + 12), QPointF(card_x + card_w, card_y + 12))
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.GOLD, 240), 1))
        p.drawText(QRectF(card_x + 4, card_y + 2, card_w - 8, 10),
                   Qt.AlignmentFlag.AlignLeft, "TGT LOCK  " + sel_label)
        sel_lat, sel_lon = _WORLD_NODES[sel_idx][0], _WORLD_NODES[sel_idx][1]
        lat_str = f"{abs(sel_lat):.1f}°{'N' if sel_lat >= 0 else 'S'}"
        lon_str = f"{abs(sel_lon):.1f}°{'E' if sel_lon >= 0 else 'W'}"
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT, 220), 1))
        p.drawText(QRectF(card_x + 4, card_y + 14, card_w - 8, 11),
                   Qt.AlignmentFlag.AlignLeft, f"LAT  {lat_str}")
        p.drawText(QRectF(card_x + 4, card_y + 25, card_w - 8, 11),
                   Qt.AlignmentFlag.AlignLeft, f"LON  {lon_str}")

        # THREAT card
        tc_x, tc_y, tc_w, tc_h = mx + mw - 120, my + 6, 112, 38
        p.setPen(QPen(qcol(C.DANGER, 180), 0.8))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
        p.drawRect(QRectF(tc_x, tc_y, tc_w, tc_h))
        p.setPen(QPen(qcol(C.DANGER, 200), 0.8))
        p.drawLine(QPointF(tc_x, tc_y + 12), QPointF(tc_x + tc_w, tc_y + 12))
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.DANGER, 240), 1))
        p.drawText(QRectF(tc_x + 4, tc_y + 2, tc_w - 8, 10),
                   Qt.AlignmentFlag.AlignLeft, "THREAT  ASSESSMENT")
        n_high = sum(1 for t in _WORLD_THREATS if t[3] == 3)
        n_med = sum(1 for t in _WORLD_THREATS if t[3] == 2)
        n_low = sum(1 for t in _WORLD_THREATS if t[3] == 1)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.DANGER, 230), 1))
        p.drawText(QRectF(tc_x + 4, tc_y + 14, tc_w - 8, 10),
                   Qt.AlignmentFlag.AlignLeft, f"HIGH  {n_high}    MED  {n_med}    LOW  {n_low}")
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.AMBER, 220), 0.8))
        lvl = "ELEVATED" if n_high > 0 else ("NORMAL" if n_high + n_med == 0 else "GUARDED")
        p.drawText(QRectF(tc_x + 4, tc_y + 26, tc_w - 8, 10),
                   Qt.AlignmentFlag.AlignLeft, "STATUS  " + lvl)

        # Footer + sub-footer
        n_nodes = len(_WORLD_NODES)
        n_links = len(_WORLD_LINKS)
        n_threats = len(_WORLD_THREATS)
        live_pkt = int(self._tick * 7) % 99999
        foot_y = y + h - 32
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(x + 30, foot_y, w - 60, 11),
                   Qt.AlignmentFlag.AlignLeft,
                   f"NODES  {n_nodes:02d}   LINKS  {n_links:02d}   THREATS  {n_threats:02d}   "
                   f"SCAN  {int(scan_t*100):03d}%   SIG  STRONG")
        p.drawText(QRectF(x + 30, foot_y, w - 60, 11),
                   Qt.AlignmentFlag.AlignRight,
                   f"PKT  {live_pkt:05d}   TGT  {sel_label}")
        foot2_y = foot_y + 12
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MUTED, 200), 0.8))
        alt = 18000 + int(800 * math.sin(self._tick * 0.2))
        rng_km = int(2000 + 1500 * math.sin(self._tick * 0.15))
        p.drawText(QRectF(x + 30, foot2_y, w - 60, 10),
                   Qt.AlignmentFlag.AlignLeft,
                   f"ALT  {alt:05d}ft   RANGE  {rng_km:04d}km   HDG  {int(self._time_phase*30)%360:03d}°   "
                   f"ZOOM  1.0x   GRID  15°")

    def _draw_core_panel_frame(self, p, x, y, w, h, color, idx):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 8, 8)
        p.setPen(QPen(qcol(C.BORDER, 160), 1))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 180)))
        p.drawPath(path)
        pulse = 0.5 + 0.5 * math.sin(self._time_phase * 1.6 + int(idx) * 0.7)
        p.setPen(QPen(qcol(color, int(160 + 70 * pulse)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # corner brackets
        cl = 10
        for (cx, cy, dx1, dy1, dx2, dy2) in [
            (x, y, cl, 0, 0, cl),
            (x + w, y, -cl, 0, 0, cl),
            (x, y + h, cl, 0, 0, -cl),
            (x + w, y + h, -cl, 0, 0, -cl),
        ]:
            p.setPen(QPen(qcol(color, 200), 1.4))
            p.drawLine(QPointF(cx + dx1, cy + dy1), QPointF(cx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx2, cy + dy2))
        # index label
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(color, 200), 1))
        p.drawText(QRectF(x + 10, y + 6, 40, 12), Qt.AlignmentFlag.AlignLeft, "SYS_" + idx)
        p.setPen(QPen(qcol(C.TEXT_MUTED, 180), 1))
        p.drawText(QRectF(x + w - 30, y + 6, 22, 12),
                   Qt.AlignmentFlag.AlignRight, "OK" if self.state != "MUTED" else "MUTED")

    def _panel_title(self, p, x, y, w, text, color):
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(qcol(color, 230), 1))
        p.drawText(QRectF(x, y, w - 90, 16), Qt.AlignmentFlag.AlignLeft, text)
        # animated bar under title
        bw = 30 + 14 * math.sin(self._time_phase * 2.4)
        p.setPen(QPen(qcol(color, 200), 1.5))
        p.drawLine(QPointF(x, y + 20), QPointF(x + bw, y + 20))

    def _draw_voice_spectrum(self, p, x, y, w, h):
        self._panel_title(p, x, y, w, "VOICE SPECTRUM", C.ACCENT)
        # Subtitle with live level
        al = self._audio_level
        sub_color = C.SUCCESS if al > 0.4 else (C.ACCENT if al > 0.1 else C.TEXT_DIM)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(sub_color, 220), 1))
        p.drawText(QRectF(x, y, w - 6, 14),
                   Qt.AlignmentFlag.AlignRight,
                   "INPUT  " + f"{al*100:5.1f}%")
        # Bars
        n = len(self._spectrum)
        bar_area_y = y + 32
        bar_area_h = h - 60
        gap = 2
        bw = (w - gap * (n - 1)) / n
        for i, v in enumerate(self._spectrum):
            bh = max(2.0, v * bar_area_h)
            bx = x + i * (bw + gap)
            by = bar_area_y + (bar_area_h - bh)
            # bar color intensity by height
            intensity = min(1.0, v * 1.4)
            col = C.ACCENT_BR if v > 0.7 else (C.ACCENT if v > 0.35 else "#1a4a6a")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(col, int(160 + 90 * intensity))))
            p.drawRect(QRectF(bx, by, bw, bh))
            # peak marker
            if v > 0.85:
                p.setBrush(QBrush(qcol("#ffffff", 220)))
                p.drawRect(QRectF(bx, by - 2, bw, 2))
        # Bottom info row
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(x, y + h - 18, w / 2, 12),
                   Qt.AlignmentFlag.AlignLeft, "FFT  40-BIN  //  16kHz")
        peak_idx = max(range(n), key=lambda i: self._spectrum[i])
        peak_hz = int(50 + (peak_idx / n) * 7950)
        p.drawText(QRectF(x, y + h - 18, w, 12),
                   Qt.AlignmentFlag.AlignRight, "PEAK  " + str(peak_hz) + " Hz")

    def _draw_tool_arsenal(self, p, x, y, w, h):
        self._panel_title(p, x, y, w, "TOOL ARSENAL", C.VIOLET)
        total = sum(self._tool_stats.values())
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.VIOLET, 220), 1))
        p.drawText(QRectF(x, y, w - 6, 14),
                   Qt.AlignmentFlag.AlignRight,
                   f"{total} INVOCATIONS")
        # Sort tools by usage
        items = sorted(self._tool_stats.items(), key=lambda kv: -kv[1])[:8]
        if not items:
            p.setFont(QFont("Courier New", 8))
            p.setPen(QPen(qcol(C.TEXT_MUTED, 200), 1))
            p.drawText(QRectF(x, y + 32, w, 30),
                       Qt.AlignmentFlag.AlignCenter,
                       "No tools invoked yet.\nAsk AEGIS to do something.")
            return
        max_count = max(c for _, c in items)
        row_h = 18
        bar_x = x + 96
        bar_w = w - 100
        base_y = y + 30
        for i, (name, count) in enumerate(items):
            ry = base_y + i * row_h
            if ry + row_h > y + h - 4: break
            p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT, 220), 1))
            short = name.replace("_", " ")[:14]
            p.drawText(QRectF(x, ry, 90, 12), Qt.AlignmentFlag.AlignLeft, short.upper())
            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qcol(C.TEXT_DIM, 220), 1))
            p.drawText(QRectF(x, ry + 11, 90, 10),
                       Qt.AlignmentFlag.AlignLeft, f"{count}x")
            # bar
            ratio = count / max(max_count, 1)
            bw = max(4, ratio * bar_w)
            color = C.VIOLET if count == max_count else "#5a3a8a"
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(color, 180)))
            p.drawRect(QRectF(bar_x, ry + 2, bw, 10))
            # pulse on top tool
            if i == 0:
                pulse = 0.5 + 0.5 * math.sin(self._time_phase * 4.0)
                p.setBrush(QBrush(qcol("#ffffff", int(140 * pulse))))
                p.drawRect(QRectF(bar_x, ry + 2, bw, 10))

    def _draw_system_vitals(self, p, x, y, w, h):
        self._panel_title(p, x, y, w, "CORE VITALS", C.GOLD)
        # status
        worst = max(self._cpu_pct, self._mem_pct)
        stat = "NOMINAL" if worst < 70 else ("ELEVATED" if worst < 88 else "CRITICAL")
        st_color = C.SUCCESS if worst < 70 else (C.WARNING if worst < 88 else C.DANGER)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(st_color, 220), 1))
        p.drawText(QRectF(x, y, w - 6, 14),
                   Qt.AlignmentFlag.AlignRight, stat)
        base_y = y + 32
        row_h = 32
        metrics = [
            ("CPU",  self._cpu_pct,    C.ACCENT,   self._cpu_history),
            ("MEM",  self._mem_pct,    C.GOLD,     self._mem_history),
            ("NET",  min(100, self._network_ms / 2.0), C.ROSE, self._net_history),
        ]
        for i, (label, val, col, hist) in enumerate(metrics):
            ry = base_y + i * row_h
            if ry + row_h > y + h - 4: break
            # label
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(col, 220), 1))
            p.drawText(QRectF(x, ry, 50, 14), Qt.AlignmentFlag.AlignLeft, label)
            # value
            if label == "NET":
                val_text = f"{self._network_ms:5.1f}ms"
            else:
                val_text = f"{val:5.1f}%"
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT, 230), 1))
            p.drawText(QRectF(x, ry, w, 14),
                       Qt.AlignmentFlag.AlignRight, val_text)
            # gauge bar
            bar_y = ry + 18
            bar_h = 6
            bar_w = w
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
            p.drawRect(QRectF(x, bar_y, bar_w, bar_h))
            fw = max(2, val / 100.0 * bar_w)
            grad = QLinearGradient(x, bar_y, x + bar_w, bar_y)
            grad.setColorAt(0.0, qcol(col, 180))
            grad.setColorAt(1.0, qcol(col, 240))
            p.setBrush(QBrush(grad))
            p.drawRect(QRectF(x, bar_y, fw, bar_h))
            # sparkline (mini history) below the bar
            if len(hist) >= 2:
                sp_y = bar_y + bar_h + 2
                sp_h = 8
                pts = []
                for j, h_v in enumerate(hist):
                    px = x + (j / max(1, len(hist) - 1)) * bar_w
                    norm = h_v / (100.0 if label != "NET" else 200.0)
                    norm = min(1.0, max(0.0, norm))
                    py = sp_y + sp_h - norm * sp_h
                    pts.append(QPointF(px, py))
                if len(pts) >= 2:
                    ppath = QPainterPath()
                    ppath.moveTo(pts[0])
                    for pt in pts[1:]:
                        ppath.lineTo(pt)
                    p.setPen(QPen(qcol(col, 200), 1))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(ppath)

    def _draw_event_stream(self, p, x, y, w, h):
        self._panel_title(p, x, y, w, "EVENT STREAM", C.ROSE)
        # LIVE indicator
        live_pulse = 0.5 + 0.5 * math.sin(self._time_phase * 5.0)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ROSE, 220), 1))
        p.drawText(QRectF(x, y, w - 6, 14),
                   Qt.AlignmentFlag.AlignRight, "LIVE")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.ROSE, int(160 + 80 * live_pulse))))
        p.drawEllipse(QPointF(x + w - 30, y + 7), 3, 3)
        # Events
        ev = self._event_log[-10:]
        if not ev:
            p.setFont(QFont("Courier New", 8))
            p.setPen(QPen(qcol(C.TEXT_MUTED, 200), 1))
            p.drawText(QRectF(x, y + 32, w, 30),
                       Qt.AlignmentFlag.AlignCenter,
                       "Awaiting system events...")
            return
        ev = list(reversed(ev))
        row_h = 14
        ev_y = y + 30
        for i, e in enumerate(ev):
            ry = ev_y + i * row_h
            if ry + row_h > y + h - 4: break
            t = e["time"].strftime("%H:%M:%S")
            kind = e["kind"]
            txt = e["text"]
            if len(txt) > 32: txt = txt[:29] + "..."
            # color by kind
            if kind == "tool":
                col = C.ACCENT
                tag = "T"
            elif kind == "cmd":
                col = C.VIOLET
                tag = "C"
            elif kind == "ok":
                col = C.SUCCESS
                tag = "OK"
            elif kind == "ui":
                col = C.GOLD
                tag = "U"
            else:
                col = C.TEXT_DIM
                tag = "."
            # tag box
            tag_x = x
            p.setPen(QPen(qcol(col, 180), 1))
            p.setBrush(QBrush(qcol(col, 30)))
            p.drawRect(QRectF(tag_x, ry + 1, 14, 11))
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(col, 240), 1))
            p.drawText(QRectF(tag_x, ry + 1, 14, 11),
                       Qt.AlignmentFlag.AlignCenter, tag)
            # time + text
            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qcol(C.TEXT_MUTED, 220), 1))
            p.drawText(QRectF(tag_x + 18, ry + 1, 50, 11),
                       Qt.AlignmentFlag.AlignLeft, t)
            p.setPen(QPen(qcol(C.TEXT, 220), 1))
            p.drawText(QRectF(tag_x + 70, ry + 1, w - 70, 11),
                       Qt.AlignmentFlag.AlignLeft, txt)

    def _layers_icon(self, p, cx, cy):
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            y = cy - 8 + i * 8
            pts = [
                QPointF(cx, y - 5),
                QPointF(cx + 12, y),
                QPointF(cx, y + 5),
                QPointF(cx - 12, y),
            ]
            p.drawPolygon(QPolygonF(pts))

    def _cube_icon(self, p, cx, cy, size):
        s = size
        p.setPen(QPen(qcol(C.ACCENT, 220), 2))
        p.setBrush(QBrush(qcol(C.ACCENT, 25)))
        top = QPolygonF([
            QPointF(cx, cy - s), QPointF(cx + s * 0.85, cy - s * 0.5),
            QPointF(cx, cy), QPointF(cx - s * 0.85, cy - s * 0.5),
        ])
        p.drawPolygon(top)
        left = QPolygonF([
            QPointF(cx - s * 0.85, cy - s * 0.5), QPointF(cx, cy),
            QPointF(cx, cy + s * 0.85), QPointF(cx - s * 0.85, cy + s * 0.35),
        ])
        p.drawPolygon(left)
        right = QPolygonF([
            QPointF(cx + s * 0.85, cy - s * 0.5), QPointF(cx, cy),
            QPointF(cx, cy + s * 0.85), QPointF(cx + s * 0.85, cy + s * 0.35),
        ])
        p.drawPolygon(right)
        p.setPen(QPen(qcol(C.ACCENT_BR, 150), 1))
        p.drawLine(QPointF(cx, cy - s), QPointF(cx, cy + s * 0.85))
        ang = self._time_phase * 0.8
        for r, a in [(s * 0.4, 0), (s * 0.55, math.pi), (s * 0.7, math.pi / 2)]:
            dx = cx + r * math.cos(ang + a)
            dy = cy + r * 0.3 * math.sin(ang + a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.ACCENT_BR, 220)))
            p.drawEllipse(QPointF(dx, dy), 3, 3)

    # ----- Right column (chat / notes / tasks) -----
    def _sync_edits(self):
        self._line_edit.setVisible(self._active_tab == 0)
        self._note_edit.setVisible(self._active_tab == 1)
        self._task_edit.setVisible(self._active_tab == 2)

    def _draw_right_column(self, p, x, y, w, h):
        self._sync_edits()
        self._panel(p, x + 14, y + 14, w - 28, h - 28, radius=14)
        if self._active_tab == 1:
            self._draw_notes_panel(p, x, y, w, h)
        elif self._active_tab == 2:
            self._draw_tasks_panel(p, x, y, w, h)
        else:
            self._draw_chat_panel(p, x, y, w, h)

    # ----- Chat panel (intelligence) -----
    def _draw_chat_panel(self, p, x, y, w, h):
        p.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT, 240), 1))
        p.drawText(QRectF(x + 30, y + 30, w - 160, 22),
                   Qt.AlignmentFlag.AlignLeft, "SYSTEM_TRANSCRIPTION")
        tab_x = x + w - 130
        tab_y = y + 26
        self._mini_tabs = []
        self._mini_tabs.append((QRectF(tab_x,      tab_y, 60, 22), "CHAT"))
        self._mini_tabs.append((QRectF(tab_x + 65, tab_y, 60, 22), "CALL"))
        self._mini_tab(p, tab_x,      tab_y, 60, 22, "CHAT", active=(self._active_right_tab == "CHAT"))
        self._mini_tab(p, tab_x + 65, tab_y, 60, 22, "CALL", active=(self._active_right_tab == "CALL"))

        ts_y = y + 60
        ds_label = "● DEEP SEARCHING..." if self._deep_search else "○ DEEP SEARCH OFF"
        ds_color = C.ACCENT if self._deep_search else C.TEXT_DIM
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(ds_color, 220), 1))
        p.drawText(QRectF(x + 30, ts_y, 200, 16),
                   Qt.AlignmentFlag.AlignLeft, ds_label)
        tog_x = x + w - 64
        tog_y = ts_y + 1
        tog_w, tog_h = 36, 16
        self._toggle_rect = QRectF(tog_x, tog_y, tog_w, tog_h)
        tog_path = QPainterPath()
        tog_path.addRoundedRect(self._toggle_rect, tog_h / 2, tog_h / 2)
        tog_fill = C.ACCENT if self._deep_search else C.BORDER
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(tog_fill, 80)))
        p.drawPath(tog_path)
        p.setPen(QPen(qcol(tog_fill, 220), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(tog_path)
        knob_x = (tog_x + tog_w - 10) if self._deep_search else (tog_x + 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.ACCENT_BR if self._deep_search else C.TEXT_DIM, 240)))
        p.drawEllipse(QPointF(knob_x, tog_y + tog_h / 2), 6, 6)

        sep_y = ts_y + 26
        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        p.drawLine(QPointF(x + 30, sep_y), QPointF(x + w - 30, sep_y))

        # ── Proactive Memory Recall chips (inline, above messages) ──
        cur_y = sep_y + 6
        if self._recalls:
            # Show up to 2 most recent
            for rec in self._recalls[-2:]:
                chip_h = 22
                chip_w = w - 60
                chip_x = x + 30
                chip_rect = QRectF(chip_x, cur_y, chip_w, chip_h)
                chip_path = QPainterPath()
                chip_path.addRoundedRect(chip_rect, 6, 6)
                p.setPen(QPen(qcol(C.VIOLET, 180), 1))
                p.setBrush(QBrush(qcol(C.VIOLET, 25)))
                p.drawPath(chip_path)
                # icon
                p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
                p.setPen(QPen(qcol(C.VIOLET, 240), 1))
                p.drawText(QRectF(chip_x + 6, cur_y, 80, chip_h),
                           Qt.AlignmentFlag.AlignVCenter, "💭 recall")
                # fact text
                p.setFont(QFont("Segoe UI", 7))
                p.setPen(QPen(qcol(C.ACCENT_BR, 230), 1))
                fact_txt = rec["fact"][:90] + ("…" if len(rec["fact"]) > 90 else "")
                p.drawText(QRectF(chip_x + 86, cur_y, chip_w - 96, chip_h),
                           Qt.AlignmentFlag.AlignVCenter, fact_txt)
                cur_y += chip_h + 4

        # ── Reasoning Trace (collapsible) ──
        if self._show_trace and self._trace_events:
            # Header
            tr_h = 18
            tr_x = x + 30
            tr_w = w - 60
            tr_rect = QRectF(tr_x, cur_y, tr_w, tr_h)
            p.setPen(QPen(qcol(C.BORDER, 140), 1))
            p.setBrush(QBrush(qcol(C.PANEL_DARK, 180)))
            header_path = QPainterPath()
            header_path.addRoundedRect(tr_rect, 4, 4)
            p.drawPath(header_path)
            arrow = "▼" if not self._trace_collapsed else "▶"
            p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.ACCENT, 220), 1))
            last_kind = self._trace_events[-1]["kind"] if self._trace_events else "—"
            last_msg  = self._trace_events[-1]["msg"][:60] if self._trace_events else ""
            p.drawText(QRectF(tr_x + 6, cur_y, tr_w - 12, tr_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"{arrow} TRACE ({len(self._trace_events)})")
            p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
            p.drawText(QRectF(tr_x + 6, cur_y, tr_w - 12, tr_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{last_kind}: {last_msg}")
            cur_y += tr_h + 4
            # Events (only if not collapsed, last 4)
            if not self._trace_collapsed:
                for ev in self._trace_events[-4:]:
                    ev_h = 16
                    kind_color = {
                        "thought": C.ACCENT_BR,
                        "tool":     C.ACCENT,
                        "result":   C.SUCCESS,
                        "plan":     C.VIOLET,
                        "error":    C.DANGER,
                    }.get(ev["kind"], C.TEXT_DIM)
                    icon = {
                        "thought": "▸",
                        "tool":    "⚙",
                        "result":  "✓",
                        "plan":    "❖",
                        "error":   "✗",
                    }.get(ev["kind"], "·")
                    p.setFont(QFont("Consolas", 7))
                    p.setPen(QPen(qcol(kind_color, 220), 1))
                    p.drawText(QRectF(tr_x + 4, cur_y, 22, ev_h),
                               Qt.AlignmentFlag.AlignVCenter, icon)
                    p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
                    t_str = ev["t"].strftime("%H:%M:%S")
                    p.drawText(QRectF(tr_x + 22, cur_y, 50, ev_h),
                               Qt.AlignmentFlag.AlignVCenter, t_str)
                    p.setPen(QPen(qcol(C.TEXT, 200), 1))
                    p.drawText(QRectF(tr_x + 70, cur_y, tr_w - 78, ev_h),
                               Qt.AlignmentFlag.AlignVCenter, ev["msg"][:80])
                    cur_y += ev_h
                cur_y += 4
        # Make sure trace/recall rects are clickable
        self._trace_toggle_rect = QRectF(x + 30, sep_y + 6, w - 60, 18) \
            if self._show_trace and self._trace_events else QRectF()

        msg_y = cur_y + 6
        msg_h = (y + h - 80) - msg_y
        messages = self._log[-8:] if self._log else []
        if not messages:
            p.setFont(QFont("Courier New", 9))
            p.setPen(QPen(qcol(C.TEXT_MUTED), 1))
            p.drawText(QRectF(x + 30, msg_y + 20, w - 60, 40),
                       Qt.AlignmentFlag.AlignCenter, "Awaiting conversation...")
        else:
            cur_y = msg_y
            for entry in messages:
                t   = entry["time"].strftime("%H:%M:%S")
                txt = entry["text"]
                kind = entry["kind"]
                if len(txt) > 220:
                    txt = txt[:217] + "..."
                line_h = 13
                if kind == "user":
                    avail = w - 80
                    n_lines = max(2, len(txt) // 32 + 1)
                    bh = 22 + n_lines * line_h
                    bx = x + w - 30 - avail
                    if cur_y + bh > msg_y + msg_h: break
                    self._msg_bubble(p, bx, cur_y, avail, bh, txt, t, "YOU", is_user=True)
                elif kind == "assistant":
                    avail = w - 80
                    n_lines = max(2, len(txt) // 32 + 1)
                    bh = 22 + n_lines * line_h
                    if cur_y + bh > msg_y + msg_h: break
                    self._msg_bubble(p, x + 30, cur_y, avail, bh, txt, t, "AEGIS", is_user=False)
                elif kind == "error":
                    p.setFont(QFont("Courier New", 8))
                    p.setPen(QPen(qcol(C.DANGER, 200), 1))
                    p.drawText(QRectF(x + 30, cur_y, w - 60, 14),
                               Qt.AlignmentFlag.AlignLeft, "⚠ " + txt[:60])
                    bh = 16
                else:
                    p.setFont(QFont("Courier New", 8))
                    p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
                    p.drawText(QRectF(x + 30, cur_y, w - 60, 14),
                               Qt.AlignmentFlag.AlignLeft, "// " + txt[:60])
                    bh = 16
                cur_y += bh + 6

        in_y = y + h - 64
        in_x = x + 30
        in_w = w - 60
        in_h = 36
        self._input_rect = QRectF(in_x, in_y, in_w - 64, in_h)
        self._line_edit.setGeometry(
            int(in_x + 8), int(in_y + 2),
            int((in_w - 64) - 16), int(in_h - 4),
        )
        if not self._line_edit.isVisible() and self._ready_chat:
            self._line_edit.show()
        in_path = QPainterPath()
        in_path.addRoundedRect(QRectF(in_x, in_y, in_w - 64, in_h), in_h / 2, in_h / 2)
        p.setPen(QPen(qcol(C.BORDER, 200), 1))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
        p.drawPath(in_path)
        p.setFont(QFont("Courier New", 9))
        if self._line_edit.isVisible() and self._line_edit.hasFocus():
            p.setPen(QPen(qcol(self._r_color[0], 150), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            focus_path = QPainterPath()
            focus_path.addRoundedRect(QRectF(in_x, in_y, in_w - 64, in_h), in_h / 2, in_h / 2)
            p.drawPath(focus_path)
        p.setFont(QFont("Courier New", 9))
        p.setPen(QPen(qcol(C.TEXT_DIM, 150), 1))
        if not (self._line_edit.isVisible() and self._line_edit.hasFocus()):
            p.drawText(QRectF(in_x + 14, in_y, in_w - 90, in_h),
                       Qt.AlignmentFlag.AlignVCenter, "Email / URL / Phone")
        send_x = in_x + in_w - 56
        send_w = 50
        self._send_rect = QRectF(send_x, in_y, send_w, in_h)
        send_path = QPainterPath()
        send_path.addRoundedRect(self._send_rect, in_h / 2, in_h / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(self._r_color[0], 200)))
        p.drawPath(send_path)
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.BG, 240), 1))
        p.drawText(QRectF(send_x, in_y, send_w, in_h),
                   Qt.AlignmentFlag.AlignCenter, "SEND")

    # ----- Notes panel -----
    _NOTE_CAT_COLOR = {
        "general":  ("#00d4ff", "#001a22"),
        "study":    ("#4ade80", "#001a10"),
        "idea":     ("#ffcc66", "#1a1400"),
        "todo":     ("#ffb347", "#1a0a00"),
        "personal": ("#a86bff", "#160022"),
        "work":     ("#ff6b9d", "#1a0008"),
    }
    _NOTE_CAT_ICON = {
        "general": "NOTE", "study": "STUDY", "idea": "IDEA",
        "todo": "TODO", "personal": "ME", "work": "WORK",
    }

    def _draw_notes_panel(self, p, x, y, w, h):
        title_color = C.AMBER
        p.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        p.setPen(QPen(qcol(title_color, 240), 1))
        p.drawText(QRectF(x + 30, y + 30, w - 160, 22),
                   Qt.AlignmentFlag.AlignLeft, "NOTES & JOURNAL")
        count = len(self._notes)
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(x + 30, y + 52, w - 60, 14),
                   Qt.AlignmentFlag.AlignLeft, f"{count} NOTE(S) SAVED")
        p.setPen(QPen(qcol(title_color, 180), 1))
        p.drawText(QRectF(x + w - 100, y + 30, 70, 18),
                   Qt.AlignmentFlag.AlignRight, "DISK SYNC")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.SUCCESS, 200)))
        p.drawEllipse(QPointF(x + w - 26, y + 39), 4, 4)

        sep_y = y + 78
        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        p.drawLine(QPointF(x + 30, sep_y), QPointF(x + w - 30, sep_y))

        list_y = sep_y + 10
        list_h = h - 200
        self._note_del_rects = []
        if not self._notes:
            p.setFont(QFont("Courier New", 9))
            p.setPen(QPen(qcol(C.TEXT_MUTED, 180), 1))
            p.drawText(QRectF(x + 30, list_y + 30, w - 60, 60),
                       Qt.AlignmentFlag.AlignCenter,
                       "No notes yet.\nType below to add one.")
        else:
            cur_y = list_y
            n_shown = 0
            max_show = 6
            for note in self._notes:
                if n_shown >= max_show: break
                cat = note.get("category", "general")
                fg, _bg = self._NOTE_CAT_COLOR.get(cat, ("#00d4ff", "#001a22"))
                icon = self._NOTE_CAT_ICON.get(cat, "NOTE")
                card_h = 56
                if cur_y + card_h > list_y + list_h: break
                card_x = x + 30
                card_w = w - 60
                card_path = QPainterPath()
                card_path.addRoundedRect(QRectF(card_x, cur_y, card_w, card_h), 6, 6)
                p.setPen(QPen(qcol(fg, 150), 1))
                p.setBrush(QBrush(qcol("#0e1525", 220)))
                p.drawPath(card_path)
                p.setPen(QPen(qcol(fg, 220), 1))
                p.setBrush(QBrush(qcol(fg, 35)))
                p.drawRect(QRectF(card_x, cur_y, 4, card_h))
                p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
                p.setPen(QPen(qcol(fg, 220), 1))
                p.drawText(QRectF(card_x + 12, cur_y + 4, 50, 11),
                           Qt.AlignmentFlag.AlignLeft, icon)
                p.setFont(QFont("Courier New", 7))
                p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
                p.drawText(QRectF(card_x + 60, cur_y + 4, card_w - 110, 11),
                           Qt.AlignmentFlag.AlignLeft, note.get("timestamp", ""))
                p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
                p.setPen(QPen(qcol(C.TEXT, 240), 1))
                title = note.get("title", "Note")
                if len(title) > 40: title = title[:37] + "..."
                p.drawText(QRectF(card_x + 12, cur_y + 17, card_w - 60, 13),
                           Qt.AlignmentFlag.AlignLeft, title)
                p.setFont(QFont("Courier New", 8))
                p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
                body = note.get("body", "")
                if len(body) > 50: body = body[:47] + "..."
                p.drawText(QRectF(card_x + 12, cur_y + 32, card_w - 60, 18),
                           Qt.TextFlag.TextWordWrap, body)
                del_w = 18
                del_h = 14
                del_x = card_x + card_w - del_w - 6
                del_y = cur_y + 6
                del_rect = QRectF(del_x, del_y, del_w, del_h)
                self._note_del_rects.append((del_rect, int(note.get("id", 0))))
                del_path = QPainterPath()
                del_path.addRoundedRect(del_rect, 3, 3)
                p.setPen(QPen(qcol(C.DANGER, 180), 1))
                p.setBrush(QBrush(qcol(C.DANGER, 25)))
                p.drawPath(del_path)
                p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
                p.setPen(QPen(qcol(C.DANGER, 230), 1))
                p.drawText(del_rect, Qt.AlignmentFlag.AlignCenter, "DEL")
                cur_y += card_h + 6
                n_shown += 1
            if len(self._notes) > max_show:
                p.setFont(QFont("Courier New", 7))
                p.setPen(QPen(qcol(C.TEXT_MUTED, 180), 1))
                p.drawText(QRectF(x + 30, cur_y + 4, w - 60, 12),
                           Qt.AlignmentFlag.AlignLeft,
                           f"+ {len(self._notes) - max_show} more note(s) on disk")

        in_y = y + h - 64
        in_x = x + 30
        in_w = w - 60
        in_h = 36
        self._note_input_rect = QRectF(in_x, in_y, in_w - 64, in_h)
        self._note_edit.setGeometry(
            int(in_x + 8), int(in_y + 2),
            int((in_w - 64) - 16), int(in_h - 4),
        )
        if not self._note_edit.isVisible():
            self._note_edit.show()
        in_path = QPainterPath()
        in_path.addRoundedRect(QRectF(in_x, in_y, in_w - 64, in_h), in_h / 2, in_h / 2)
        p.setPen(QPen(qcol(C.AMBER, 200), 1))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
        p.drawPath(in_path)
        if self._note_edit.hasFocus():
            p.setPen(QPen(qcol(C.AMBER, 150), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            fp = QPainterPath()
            fp.addRoundedRect(QRectF(in_x, in_y, in_w - 64, in_h), in_h / 2, in_h / 2)
            p.drawPath(fp)
        p.setFont(QFont("Courier New", 9))
        p.setPen(QPen(qcol(C.TEXT_DIM, 150), 1))
        if not (self._note_edit.isVisible() and self._note_edit.hasFocus()):
            p.drawText(QRectF(in_x + 14, in_y, in_w - 90, in_h),
                       Qt.AlignmentFlag.AlignVCenter, "Type a note, press Enter")
        send_x = in_x + in_w - 56
        send_w = 50
        send_rect = QRectF(send_x, in_y, send_w, in_h)
        send_path = QPainterPath()
        send_path.addRoundedRect(send_rect, in_h / 2, in_h / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.AMBER, 200)))
        p.drawPath(send_path)
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.BG, 240), 1))
        p.drawText(send_rect, Qt.AlignmentFlag.AlignCenter, "SAVE")
        self._note_send_rect = send_rect

    # ----- Tasks panel -----
    _TASK_PRIO_COLOR = {
        "high":   ("#ff3a5c", "#1a0008"),
        "medium": ("#ffb347", "#1a1100"),
        "low":    ("#7fc8ff", "#001a22"),
    }
    _TASK_PRIO_LABEL = {"high": "HIGH", "medium": "MED", "low": "LOW"}

    def _draw_tasks_panel(self, p, x, y, w, h):
        title_color = C.ROSE
        p.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        p.setPen(QPen(qcol(title_color, 240), 1))
        p.drawText(QRectF(x + 30, y + 30, w - 160, 22),
                   Qt.AlignmentFlag.AlignLeft, "TASK CONTROL")
        pending = sum(1 for t in self._tasks if not t.get("done"))
        done    = sum(1 for t in self._tasks if t.get("done"))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(x + 30, y + 52, w - 60, 14),
                   Qt.AlignmentFlag.AlignLeft,
                   f"{pending} PENDING  /  {done} COMPLETE")
        self._task_clear_rect = QRectF(x + w - 80, y + 30, 60, 18)
        cp = QPainterPath()
        cp.addRoundedRect(self._task_clear_rect, 3, 3)
        p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 180)))
        p.drawPath(cp)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 220), 1))
        p.drawText(self._task_clear_rect, Qt.AlignmentFlag.AlignCenter, "CLEAR DONE")

        prio_y = y + 78
        self._task_prio_rects = []
        prio_x = x + 30
        prio_w_each = 50
        for i, pr in enumerate(("high", "medium", "low")):
            prx = prio_x + i * (prio_w_each + 4)
            rect = QRectF(prx, prio_y, prio_w_each, 22)
            self._task_prio_rects.append((rect, pr))
            fg, _bg = self._TASK_PRIO_COLOR[pr]
            is_active = (self._task_priority == pr)
            pp = QPainterPath()
            pp.addRoundedRect(rect, 4, 4)
            if is_active:
                p.setPen(QPen(qcol(fg, 220), 1.2))
                p.setBrush(QBrush(qcol(fg, 40)))
            else:
                p.setPen(QPen(qcol(C.BORDER, 150), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(pp)
            p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            p.setPen(QPen(qcol(fg if is_active else C.TEXT_DIM, 230 if is_active else 180), 1))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._TASK_PRIO_LABEL[pr])

        sep_y = prio_y + 30
        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        p.drawLine(QPointF(x + 30, sep_y), QPointF(x + w - 30, sep_y))

        list_y = sep_y + 10
        list_h = h - 220
        self._task_check_rects = []
        self._task_del_rects   = []
        if not self._tasks:
            p.setFont(QFont("Courier New", 9))
            p.setPen(QPen(qcol(C.TEXT_MUTED, 180), 1))
            p.drawText(QRectF(x + 30, list_y + 30, w - 60, 60),
                       Qt.AlignmentFlag.AlignCenter,
                       "No tasks yet.\nType below to add one.")
        else:
            cur_y = list_y
            n_shown = 0
            max_show = 6
            for task in self._tasks:
                if n_shown >= max_show: break
                pr = task.get("priority", "medium")
                fg, _bg = self._TASK_PRIO_COLOR.get(pr, ("#ffb347", "#1a1100"))
                is_done = bool(task.get("done"))
                card_h = 40
                if cur_y + card_h > list_y + list_h: break
                card_x = x + 30
                card_w = w - 60
                cp = QPainterPath()
                cp.addRoundedRect(QRectF(card_x, cur_y, card_w, card_h), 5, 5)
                p.setPen(QPen(qcol(fg, 140 if not is_done else 80), 1))
                p.setBrush(QBrush(qcol("#0a1018" if is_done else "#0e1525", 220)))
                p.drawPath(cp)
                box = 16
                bx, by = card_x + 8, cur_y + (card_h - box) / 2
                box_rect = QRectF(bx, by, box, box)
                self._task_check_rects.append((box_rect, int(task.get("id", 0))))
                bp = QPainterPath()
                bp.addRoundedRect(box_rect, 3, 3)
                p.setPen(QPen(qcol(C.SUCCESS if is_done else C.BORDER, 220), 1))
                p.setBrush(QBrush(qcol(C.SUCCESS, 50) if is_done else qcol(C.PANEL_DARK, 180)))
                p.drawPath(bp)
                if is_done:
                    p.setPen(QPen(qcol(C.SUCCESS, 240), 2))
                    p.drawLine(QPointF(bx + 3, by + box / 2),
                               QPointF(bx + box / 2 - 1, by + box - 3))
                    p.drawLine(QPointF(bx + box / 2 - 1, by + box - 3),
                               QPointF(bx + box - 2, by + 3))
                p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
                p.setPen(QPen(qcol(fg, 220), 1))
                p.drawText(QRectF(bx + box + 6, cur_y + 4, 40, 11),
                           Qt.AlignmentFlag.AlignLeft, self._TASK_PRIO_LABEL[pr])
                p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
                p.setPen(QPen(qcol(C.TEXT_MUTED if is_done else C.TEXT, 240), 1))
                txt = task.get("text", "Task")
                if len(txt) > 32: txt = txt[:29] + "..."
                p.drawText(QRectF(bx + box + 6, cur_y + 17, card_w - 80, 14),
                           Qt.AlignmentFlag.AlignLeft, txt)
                if is_done:
                    p.setPen(QPen(qcol(C.TEXT_DIM, 100), 1))
                    p.drawLine(QPointF(bx + box + 4, cur_y + 23),
                               QPointF(bx + box + 4 + 100, cur_y + 23))
                del_w, del_h = 18, 14
                dx = card_x + card_w - del_w - 6
                dy = cur_y + (card_h - del_h) / 2
                del_rect = QRectF(dx, dy, del_w, del_h)
                self._task_del_rects.append((del_rect, int(task.get("id", 0))))
                dp = QPainterPath()
                dp.addRoundedRect(del_rect, 3, 3)
                p.setPen(QPen(qcol(C.DANGER, 180), 1))
                p.setBrush(QBrush(qcol(C.DANGER, 25)))
                p.drawPath(dp)
                p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
                p.setPen(QPen(qcol(C.DANGER, 230), 1))
                p.drawText(del_rect, Qt.AlignmentFlag.AlignCenter, "DEL")
                cur_y += card_h + 5
                n_shown += 1
            if len(self._tasks) > max_show:
                p.setFont(QFont("Courier New", 7))
                p.setPen(QPen(qcol(C.TEXT_MUTED, 180), 1))
                p.drawText(QRectF(x + 30, cur_y + 4, w - 60, 12),
                           Qt.AlignmentFlag.AlignLeft,
                           f"+ {len(self._tasks) - max_show} more task(s) on disk")

        in_y = y + h - 64
        in_x = x + 30
        in_w = w - 60
        in_h = 36
        self._task_input_rect = QRectF(in_x, in_y, in_w - 64, in_h)
        self._task_edit.setGeometry(
            int(in_x + 8), int(in_y + 2),
            int((in_w - 64) - 16), int(in_h - 4),
        )
        if not self._task_edit.isVisible():
            self._task_edit.show()
        in_path = QPainterPath()
        in_path.addRoundedRect(QRectF(in_x, in_y, in_w - 64, in_h), in_h / 2, in_h / 2)
        p.setPen(QPen(qcol(C.ROSE, 200), 1))
        p.setBrush(QBrush(qcol(C.PANEL_DARK, 200)))
        p.drawPath(in_path)
        if self._task_edit.hasFocus():
            p.setPen(QPen(qcol(C.ROSE, 150), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            fp = QPainterPath()
            fp.addRoundedRect(QRectF(in_x, in_y, in_w - 64, in_h), in_h / 2, in_h / 2)
            p.drawPath(fp)
        p.setFont(QFont("Courier New", 9))
        p.setPen(QPen(qcol(C.TEXT_DIM, 150), 1))
        if not (self._task_edit.isVisible() and self._task_edit.hasFocus()):
            p.drawText(QRectF(in_x + 14, in_y, in_w - 90, in_h),
                       Qt.AlignmentFlag.AlignVCenter, "Type a task, press Enter")
        send_x = in_x + in_w - 56
        send_w = 50
        send_rect = QRectF(send_x, in_y, send_w, in_h)
        send_path = QPainterPath()
        send_path.addRoundedRect(send_rect, in_h / 2, in_h / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.ROSE, 200)))
        p.drawPath(send_path)
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.BG, 240), 1))
        p.drawText(send_rect, Qt.AlignmentFlag.AlignCenter, "ADD")
        self._task_send_rect = send_rect

    def _msg_bubble(self, p, x, y, w, h, text, time, name, is_user=False):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 10, 10)
        if is_user:
            p.setPen(QPen(qcol(C.ACCENT, 200), 1))
            p.setBrush(QBrush(qcol(C.ACCENT, 18)))
        else:
            p.setPen(QPen(qcol(C.BORDER, 150), 1))
            p.setBrush(QBrush(qcol(C.PANEL_HI, 100)))
        p.drawPath(path)
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT if is_user else C.TEXT_DIM, 220), 1))
        p.drawText(QRectF(x + 10, y + 4, w - 80, 12),
                   Qt.AlignmentFlag.AlignLeft, name)
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM, 150), 1))
        p.drawText(QRectF(x + w - 70, y + 4, 60, 12),
                   Qt.AlignmentFlag.AlignRight, time)
        p.setFont(QFont("Courier New", 9))
        p.setPen(QPen(qcol(C.TEXT, 220), 1))
        p.drawText(QRectF(x + 10, y + 18, w - 20, h - 22),
                   Qt.TextFlag.TextWordWrap, text)

    def _mini_tab(self, p, x, y, w, h, text, active=False):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.ACCENT, 50)))
            p.drawPath(path)
            p.setPen(QPen(qcol(C.ACCENT, 220), 1))
        else:
            p.setPen(QPen(qcol(C.BORDER, 150), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT_BR if active else C.TEXT_DIM, 230 if active else 180), 1))
        p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, text)

    # ----- Panel helper -----
    def _panel(self, p, x, y, w, h, radius=12):
        # OPTIMIZED: cache the QPainterPath keyed by rounded dimensions.
        # Caches cleared on resizeEvent.
        key = (round(x), round(y), round(w), round(h), int(radius))
        cached = self._panel_cache.get(key)
        if cached is None:
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, y, w, h), radius, radius)
            hl_path = QPainterPath()
            hl_path.moveTo(x + radius, y + 1)
            hl_path.lineTo(x + w - radius, y + 1)
            cached = (path, hl_path)
            self._panel_cache[key] = cached
        path, hl_path = cached
        grad = QLinearGradient(0, y, 0, y + h)
        grad.setColorAt(0.0, qcol(C.PANEL_HI, 180))
        grad.setColorAt(1.0, qcol(C.PANEL, 200))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(path)
        p.setPen(_get_pen(C.BORDER, 200, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(_get_pen(C.ACCENT, 60, 1))
        p.drawPath(hl_path)

    # ----- Effects -----
    def _draw_scan_line(self, p, W, H):
        y = self._scan_y
        grad = QLinearGradient(0, y - 30, 0, y + 30)
        grad.setColorAt(0.0, qcol(C.ACCENT, 0))
        grad.setColorAt(0.5, qcol(C.ACCENT, 22))
        grad.setColorAt(1.0, qcol(C.ACCENT, 0))
        p.fillRect(QRectF(0, y - 30, W, 60), QBrush(grad))
        p.setPen(QPen(qcol(C.ACCENT, 60), 1))
        p.drawLine(QPointF(0, y), QPointF(W, y))

    def _draw_vignette(self, p, W, H):
        vg = QRadialGradient(QPointF(W / 2, H / 2), max(W, H) * 0.75)
        vg.setColorAt(0.55, qcol("#000000", 0))
        vg.setColorAt(1.0, qcol("#000000", 180))
        p.fillRect(self.rect(), QBrush(vg))

    # ----- New visual differentiators -----
    def _draw_hex_frame(self, p, cx, cy, R):
        ring_c = self._r_color[0]
        pts = []
        for i in range(6):
            ang = math.pi / 3 * i + self._time_phase * 0.4
            pts.append(QPointF(cx + R * math.cos(ang), cy + R * math.sin(ang)))
        hex_path = QPainterPath()
        hex_path.moveTo(pts[0])
        for pt in pts[1:]:
            hex_path.lineTo(pt)
        hex_path.closeSubpath()
        p.setPen(QPen(qcol(ring_c, 90), 1.4, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(hex_path)
        inner = R * 0.78
        pts2 = []
        for i in range(6):
            ang = math.pi / 3 * i - self._time_phase * 0.6
            pts2.append(QPointF(cx + inner * math.cos(ang), cy + inner * math.sin(ang)))
        ipath = QPainterPath()
        ipath.moveTo(pts2[0])
        for pt in pts2[1:]:
            ipath.lineTo(pt)
        ipath.closeSubpath()
        p.setPen(QPen(qcol(ring_c, 180), 1))
        p.drawPath(ipath)
        for i, pt in enumerate(pts):
            ang_v = self._time_phase * 1.2 + i
            vr = R + 4 + 3 * math.sin(ang_v)
            vx = cx + vr * math.cos(math.atan2(pt.y() - cy, pt.x() - cx))
            vy = cy + vr * math.sin(math.atan2(pt.y() - cy, pt.x() - cx))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(ring_c, 230)))
            p.drawEllipse(QPointF(vx, vy), 2.2, 2.2)

    def _draw_reticle(self, p, cx, cy, r):
        ring_c = self._r_color[1]
        rot = self._time_phase * 0.8
        for ang_off in (0, math.pi / 2, math.pi / 4, 3 * math.pi / 4):
            a1 = rot + ang_off
            a2 = a1 + math.pi / 8
            p.setPen(QPen(qcol(ring_c, 200), 1.2))
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2),
                      int(math.degrees(a1) * 16), int(math.degrees(a2 - a1) * 16))
        for ang_off in (math.pi, 3 * math.pi / 2, 5 * math.pi / 4, 7 * math.pi / 4):
            a1 = rot + ang_off
            a2 = a1 + math.pi / 8
            p.setPen(QPen(qcol(ring_c, 100), 1))
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2),
                      int(math.degrees(a1) * 16), int(math.degrees(a2 - a1) * 16))
        gap = 14
        p.setPen(QPen(qcol(ring_c, 220), 1.4))
        p.drawLine(QPointF(cx - r, cy), QPointF(cx - gap, cy))
        p.drawLine(QPointF(cx + gap, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy - gap))
        p.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + r))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(ring_c, 240)))
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(ring_c, 180), 1))
        p.drawEllipse(QPointF(cx, cy), 6, 6)

    # ----- Arc Reactor (Tony Stark style, voice-reactive) -----
    def _draw_plasma_reactor(self, p, cx, cy, R):
        if self.state == "SPEAKING":
            c_outer = "#3a0800"
            c_mid   = "#ff5522"
            c_inner = "#ffaa44"
            c_core  = "#fff2c0"
        else:
            c_outer = "#001a3a"
            c_mid   = "#1a78d8"
            c_inner = "#7fc8ff"
            c_core  = "#e0f4ff"

        al  = self._audio_level
        pulse = self._reactor_pulse
        R_eff = R * (1.0 + 0.06 * al)

        # Outer glow halo (color follows state)
        halo_r = R_eff * 1.6
        halo = QRadialGradient(QPointF(cx, cy), halo_r)
        halo.setColorAt(0.0, qcol(c_mid, int(110 * pulse)))
        halo.setColorAt(0.5, qcol(c_mid, int(40 * pulse)))
        halo.setColorAt(1.0, qcol(c_mid, 0))
        p.setBrush(QBrush(halo))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        # Dark inner backdrop (filled circle - "the globe")
        bg_grad = QRadialGradient(QPointF(cx, cy), R_eff)
        bg_grad.setColorAt(0.0, qcol("#000000", 235))
        bg_grad.setColorAt(0.85, qcol(c_outer, 220))
        bg_grad.setColorAt(1.0, qcol(c_mid, 60))
        p.setBrush(QBrush(bg_grad))
        p.setPen(QPen(qcol(c_mid, 230), 2))
        p.drawEllipse(QPointF(cx, cy), R_eff, R_eff)

        # Soft inner radial glow that pulses
        inner_glow = QRadialGradient(QPointF(cx, cy), R_eff * 0.7)
        inner_glow.setColorAt(0.0, qcol(c_core, int(40 + 100 * al)))
        inner_glow.setColorAt(1.0, qcol(c_inner, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(inner_glow))
        p.drawEllipse(QPointF(cx, cy), R_eff * 0.7, R_eff * 0.7)

        # Plasma arcs — OPTIMIZED: cache pens per color/w, branch lines skip glow
        clip_path = QPainterPath()
        clip_path.addEllipse(QPointF(cx, cy), R_eff - 1, R_eff - 1)
        p.save()
        p.setClipPath(clip_path)
        # Pen cache for the 3 colors × (main 1.4 / branch 1.0)
        arc_pens = {
            (c_inner, 1.4): _get_pen(c_inner, 220, 1.4),
            (c_inner, 1.0): _get_pen(c_inner, 220, 1.0),
            (c_mid,   1.4): _get_pen(c_mid,   220, 1.4),
            (c_mid,   1.0): _get_pen(c_mid,   220, 1.0),
            (c_outer, 1.4): _get_pen(c_outer, 220, 1.4),
            (c_outer, 1.0): _get_pen(c_outer, 220, 1.0),
        }
        core_pen_main = _get_pen(c_core, 180, 0.7)
        for arc in self._plasma_arcs:
            phase = arc["phase"]
            speed = arc["speed"]
            wave = 0.5 + 0.5 * math.sin(self._time_phase * speed + phase)
            intensity = 0.25 + 0.75 * wave * (0.5 + 0.7 * al)
            pts = arc["pts"]
            is_main = (arc["kind"] == "main")
            w = 1.4 if is_main else 1.0
            for i in range(len(pts) - 1):
                x1, y1, t1 = pts[i]
                x2, y2, t2 = pts[i + 1]
                seg_wave = 0.5 + 0.5 * math.sin(self._time_phase * speed * 1.3
                                                 + phase + i * 0.7)
                seg_alpha = intensity * seg_wave
                if seg_alpha < 0.05:
                    continue
                mid_t = (t1 + t2) / 2
                if mid_t < 0.35:
                    color = c_inner
                elif mid_t < 0.75:
                    color = c_mid
                else:
                    color = c_outer
                px1 = cx + x1 * R_eff
                py1 = cy + y1 * R_eff
                px2 = cx + x2 * R_eff
                py2 = cy + y2 * R_eff
                a1 = int(255 * seg_alpha)
                p.setPen(arc_pens[(color, w)])
                p.drawLine(QPointF(px1, py1), QPointF(px2, py2))
                if is_main and seg_alpha > 0.6:
                    p.setPen(core_pen_main)
                    p.drawLine(QPointF(px1, py1), QPointF(px2, py2))
        p.restore()

        # Sparks (embers) flying outward
        clip_path2 = QPainterPath()
        clip_path2.addEllipse(QPointF(cx, cy), R_eff - 1, R_eff - 1)
        p.save()
        p.setClipPath(clip_path2)
        for sp in self._sparks:
            if sp["life"] <= 0:
                continue
            life_t = sp["life"] / sp["max_life"]
            px = cx + sp["x"] * R_eff
            py = cy + sp["y"] * R_eff
            r = sp["size"] * (0.4 + 0.6 * life_t) * (0.8 + 0.5 * al)
            color = c_core if life_t > 0.6 else (c_inner if life_t > 0.3 else c_mid)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(color, int(220 * life_t))))
            p.drawEllipse(QPointF(px, py), r, r)
            if r > 1.2:
                p.setBrush(QBrush(qcol(color, int(80 * life_t))))
                p.drawEllipse(QPointF(px, py), r * 2.5, r * 2.5)
        p.restore()

        # Re-clip for center elements
        p.save()
        p.setClipPath(clip_path)
        # Bright pulsing center
        core_r = (4 + 6 * al) * (0.9 + 0.2 * pulse)
        core_grad = QRadialGradient(QPointF(cx, cy), core_r * 2.5)
        core_grad.setColorAt(0.0, qcol("#ffffff", 255))
        core_grad.setColorAt(0.4, qcol(c_core, int(240 * pulse)))
        core_grad.setColorAt(1.0, qcol(c_inner, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(cx, cy), core_r * 2.5, core_r * 2.5)
        p.restore()

        # Outer ring bright outline
        p.setPen(QPen(qcol(c_mid, int(200 + 40 * al)), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R_eff, R_eff)
        # Subtle inner ring
        p.setPen(QPen(qcol(c_inner, int(80 * pulse)), 1))
        p.drawEllipse(QPointF(cx, cy), R_eff * 0.94, R_eff * 0.94)

        # Audio spike ripples (when level is high)
        if al > 0.35:
            n_ripples = 2
            for k in range(n_ripples):
                phase_offset = (self._time_phase * 4 + k * 0.5) % 1.0
                wave_r = R_eff + phase_offset * 22
                alpha = int(160 * (1 - phase_offset) * (al - 0.35) / 0.65)
                if alpha > 0:
                    p.setPen(QPen(qcol(c_mid, alpha), 1.2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(cx, cy), wave_r, wave_r)

    def _draw_corner_brackets(self, p, rect, length, color, alpha=220):
        # OPTIMIZED: build ONE QPainterPath for all 8 bracket segments and draw in one call.
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        key = (round(x), round(y), round(w), round(h), int(length), color, int(alpha))
        path = self._corner_cache.get(key)
        if path is None:
            path = QPainterPath()
            path.moveTo(x,           y);           path.lineTo(x + length, y)
            path.moveTo(x,           y);           path.lineTo(x,           y + length)
            path.moveTo(x + w,       y);           path.lineTo(x + w - length, y)
            path.moveTo(x + w,       y);           path.lineTo(x + w,       y + length)
            path.moveTo(x,           y + h);       path.lineTo(x + length, y + h)
            path.moveTo(x,           y + h);       path.lineTo(x,           y + h - length)
            path.moveTo(x + w,       y + h);       path.lineTo(x + w - length, y + h)
            path.moveTo(x + w,       y + h);       path.lineTo(x + w,       y + h - length)
            self._corner_cache[key] = path
        p.setPen(_get_pen(color, alpha, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_waveform(self, p, x, y, w, h):
        n = len(self._wave_samples)
        new = (math.sin(self._wave_phase * 1.7) +
               0.6 * math.sin(self._wave_phase * 3.1 + 0.7) +
               0.3 * random.uniform(-1, 1)) * 0.5
        self._wave_samples.pop(0)
        self._wave_samples.append(max(-1.0, min(1.0, new)))
        mid = y + h / 2
        path = QPainterPath()
        path.moveTo(x, mid)
        for i, s in enumerate(self._wave_samples):
            px = x + (i / (n - 1)) * w
            py = mid - s * (h / 2 - 4)
            path.lineTo(px, py)
        glow = QLinearGradient(0, y, 0, y + h)
        glow.setColorAt(0.0, qcol(C.ACCENT, 0))
        glow.setColorAt(0.5, qcol(C.ACCENT_BR, 220))
        glow.setColorAt(1.0, qcol(C.ACCENT, 0))
        p.setPen(QPen(QBrush(glow), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        for i in range(0, n, 4):
            px = x + (i / (n - 1)) * w
            py = mid - self._wave_samples[i] * (h / 2 - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.ACCENT_BR, 180)))
            p.drawEllipse(QPointF(px, py), 1.4, 1.4)
        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        p.drawLine(QPointF(x, mid), QPointF(x + w, mid))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
        p.drawText(QRectF(x, y + 2, 60, 10),
                   Qt.AlignmentFlag.AlignLeft, "AUDIO.IN")
        p.drawText(QRectF(x + w - 50, y + 2, 50, 10),
                   Qt.AlignmentFlag.AlignRight, "F.S.30Hz")

    def _draw_terminal_log(self, p, x, y, w, h):
        self._panel(p, x, y, w, h, radius=10)
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.AMBER, 220), 1))
        p.drawText(QRectF(x + 12, y + 6, w - 24, 12),
                   Qt.AlignmentFlag.AlignLeft, "▣ SYS.LOG")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM, 180), 1))
        p.drawText(QRectF(x + 12, y + 6, w - 24, 12),
                   Qt.AlignmentFlag.AlignRight, "T=" + datetime.now().strftime("%H:%M:%S"))
        visible = 4
        line_h = 13
        cy = y + 22
        sources = (self._system_log + [
            "OK  : subsystems online",
            "INFO: listening on 0.0.0.0",
            "OK  : audio input ready",
            "OK  : model layer cached",
            "INFO: v0.39 build 1001",
        ])[-visible:]
        for ln in sources:
            color = C.TEXT_DIM
            if "ERR" in ln:    color = C.DANGER
            elif "OK" in ln:   color = C.SUCCESS
            elif "INFO" in ln: color = C.ACCENT_BR
            elif "[" in ln:    color = C.AMBER
            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qcol(color, 220), 1))
            p.drawText(QRectF(x + 12, cy, w - 24, line_h),
                       Qt.AlignmentFlag.AlignLeft, ln[:60])
            cy += line_h

    def _draw_pulses(self, p):
        if not self._pulse_accents:
            return
        now = time.time()
        if now > self._pulse_until:
            self._pulse_accents = []
            return
        elapsed = self._pulse_until - now
        t = 1.0 - (elapsed / 0.35)
        kept = []
        for rect in self._pulse_accents:
            color = self._r_color[0]
            inset = 4 * t
            r2 = QRectF(rect.x() - inset, rect.y() - inset,
                        rect.width() + 2 * inset, rect.height() + 2 * inset)
            p.setPen(QPen(qcol(color, int(220 * (1 - t))), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.addRoundedRect(r2, 10, 10)
            p.drawPath(path)
            if t < 0.9:
                kept.append(rect)
        self._pulse_accents = kept


# ==================== Setup Overlay ====================
class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "SetupOverlay {"
            "  background: rgba(6, 9, 18, 245);"
            "  border: 1px solid " + C.ACCENT + ";"
            "  border-radius: 12px;"
            "}"
        )
        detected = {"darwin": "mac", "windows": "windows"}.get(_OS.lower(), "linux")
        self._sel_os = detected
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.TEXT,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet("color: " + color + "; background: transparent;")
            return w

        layout.addWidget(_lbl("?  INITIALISATION REQUIRED", 13, True, C.ACCENT))
        layout.addWidget(_lbl("Configure AEGIS before first boot.", 9, color=C.TEXT_DIM))
        layout.addSpacing(6)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: " + C.BORDER + ";"); layout.addWidget(sep)
        layout.addSpacing(4)
        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza...")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(
            "QLineEdit { background: #03091a; color: " + C.TEXT + ";"
            " border: 1px solid " + C.BORDER + "; border-radius: 3px; padding: 4px 8px; }"
            "QLineEdit:focus { border: 1px solid " + C.ACCENT + "; }"
        )
        layout.addWidget(self._key_input)
        layout.addSpacing(12)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: " + C.BORDER + ";"); layout.addWidget(sep2)
        layout.addSpacing(4)
        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl("Auto-detected: " + det_name, 8, color=C.WARNING, align=Qt.AlignmentFlag.AlignLeft))
        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns = {}
        for key, label in [("windows", "?  Windows"), ("mac", "  macOS"), ("linux", "??  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)
        init_btn = QPushButton("?  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(
            "QPushButton { background: transparent; color: " + C.ACCENT + ";"
            " border: 1px solid " + C.BORDER_HI + "; border-radius: 3px; }"
            "QPushButton:hover { background: " + C.PANEL_HI + "; border: 1px solid " + C.ACCENT + "; }"
        )
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key):
        self._sel_os = key
        pal = {"windows": (C.ACCENT, C.PANEL_DARK),
               "mac":     (C.WARNING, "#1a0d00"),
               "linux":   (C.SUCCESS, "#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(
                    "QPushButton { background: " + fg + "; color: " + bg + ";"
                    " border: none; border-radius: 3px; font-weight: bold; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background: " + C.PANEL_DARK + "; color: " + C.TEXT_DIM + ";"
                    " border: 1px solid " + C.BORDER + "; border-radius: 3px; }"
                    "QPushButton:hover { color: " + C.TEXT + "; border: 1px solid " + C.BORDER_HI + "; }"
                )

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                " QLineEdit { border: 1px solid " + C.DANGER + "; }"
            )
            return
        self.done.emit(key, self._sel_os)



# ==================== Main Window ====================
class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _tool_sig  = pyqtSignal(str)

    def __init__(self, face_path):
        super().__init__()
        self.setWindowTitle("AEGIS  -  MARK XXXIX")
        self.setWindowIcon(QIcon(str(BASE_DIR / "app_icon.png")))
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file    = None

        central = QWidget()
        central.setStyleSheet("background: " + C.BG + ";")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.hud = SciFiHud(face_path)
        root.addWidget(self.hud)

        self._log_sig.connect(self.hud.add_log)
        self._tool_sig.connect(lambda name: self.hud.notify_tool(name or None))

        self._state_sig.connect(self._apply_state)
        self.hud.action_triggered.connect(self._on_hud_action)

        self._overlay = None

        self._ready = self._check_config()
        if self._ready:
            self.hud._ready_chat = True
        else:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_mode = QShortcut(QKeySequence("Ctrl+M"), self)
        sc_mode.activated.connect(self._cycle_mode)
        # (connected after bar_win is created)

    def _on_hud_action(self, code: str):
        kind, _, val = code.partition(":")
        if kind == "send":
            if val:
                self._log_sig.emit("YOU: " + val)
                if self.on_text_command:
                    try:
                        self.on_text_command(val)
                    except Exception as exc:
                        self._log_sig.emit("ERR: text handler - " + str(exc))
            else:
                self.hud._line_edit.setFocus()
            return
        if kind == "terminate":
            self._log_sig.emit("SYS: TERMINATE command received")
            print("SYS: TERMINATE pressed - closing.")
            QTimer.singleShot(600, self.close)
            return
        if kind == "toggle":
            state_txt = "ON" if val == "1" else "OFF"
            self._log_sig.emit("SYS: Deep search toggled " + state_txt)
            return
        if kind == "tab":
            self._log_sig.emit("SYS: Switched to " + val.upper() + " tab")
            return
        if kind == "minitab":
            self._log_sig.emit("SYS: Panel mode = " + val)
            return
        if kind == "hub":
            if val == "reactor":
                self._log_sig.emit("SYS: Arc reactor pinged - core nominal")
            else:
                self._log_sig.emit("AEGIS: Visual hub activated - awaiting image input")
            return
        if kind == "card":
            label = val.replace("_", " ").upper()
            self._log_sig.emit("SYS: " + label + " panel opened")
            return
        if kind == "button":
            label = val.replace("_", " ").upper()
            self._log_sig.emit("SYS: Action " + label + " triggered")
            return
        if kind == "cmd":
            return
        if kind == "mode":
            # Mode switch is initiated internally — MainWindow.set_mode logs the result.
            return
        self._log_sig.emit("SYS: unknown action " + code)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh,
            )

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        if self._muted:
            self._apply_state("MUTED")
            print("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            print("SYS: Microphone active.")

    def _cycle_mode(self):
        new_key = self.hud.cycle_mode()
        name = MODES[new_key]["name"]
        self._log_sig.emit("SYS: Mode -> " + name)
        print("SYS: Mode -> " + name)


    def _apply_state(self, state):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        self.hud.set_reactor_state(state)

    def _check_config(self):
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key, os_name):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {}
        if API_FILE.exists():
            try:
                data = json.loads(API_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["gemini_api_key"] = key
        data["os_system"] = os_name
        API_FILE.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        self._ready = True
        self.hud._ready_chat = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        print("SYS: Initialised. OS=" + os_name.upper() + ". Aegis online.")

    def set_audio_level(self, level: float):
        self.hud.set_audio_level(level)

    def set_mode(self, name: str) -> bool:
        ok = self.hud.set_mode(name)
        if ok:
            n = MODES[name]["name"] if name in MODES else name
            self._log_sig.emit("SYS: Mode -> " + n)
        return ok

    def pin_card(self, type_: str, title: str, data: dict) -> str:
        return self.hud.pin_card(type_, title, data)

    def unpin_card(self, card_id: str) -> bool:
        return self.hud.unpin_card(card_id)

    def clear_cards(self) -> int:
        return self.hud.clear_cards()

    def has_pinned_card(self, type_: str) -> bool:
        return self.hud.has_pinned_card(type_)

    def set_card_ttl(self, seconds: float):
        self.hud.set_card_ttl(seconds)

    def add_trace(self, kind: str, msg: str) -> None:
        self.hud.add_trace(kind, msg)

    def clear_trace(self) -> None:
        self.hud.clear_trace()

    def set_show_trace(self, show: bool) -> None:
        self.hud.set_show_trace(show)

    def toggle_trace_collapsed(self) -> None:
        self.hud.toggle_trace_collapsed()

    def add_recall(self, query: str, fact: str) -> None:
        self.hud.add_recall(query, fact)

    def clear_recalls(self) -> None:
        self.hud.clear_recalls()




# ==================== Root shim + AegisUI ====================
class _RootShim:
    def __init__(self, app):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class AegisUI:
    def __init__(self, face_path, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self):
        return self._win._muted

    @muted.setter
    def muted(self, v):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self):
        return self._win._current_file

    @property
    def hud(self):
        return self._win.hud

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state):
        self._win._state_sig.emit(state)

    def write_log(self, text):
        self._win._log_sig.emit(text)

    def notify_tool(self, name=""):
        self._win._tool_sig.emit(name)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def on_action(self, callback):
        if callback is None:
            return
        self._win.hud.action_triggered.connect(callback)

    def simulate_send(self, text: str):
        self._win._log_sig.emit("YOU: " + text)
        if self._win.on_text_command:
            try:
                self._win.on_text_command(text)
            except Exception as exc:
                self._win._log_sig.emit("ERR: text command handler - " + str(exc))

    def set_audio_level(self, level: float):
        self._win.set_audio_level(level)

    def set_mode(self, name: str) -> bool:
        return self._win.set_mode(name)

    def pin_card(self, type_: str, title: str, data: dict) -> str:
        return self._win.pin_card(type_, title, data)

    def unpin_card(self, card_id: str) -> bool:
        return self._win.unpin_card(card_id)

    def clear_cards(self) -> int:
        return self._win.clear_cards()

    def has_pinned_card(self, type_: str) -> bool:
        return self._win.has_pinned_card(type_)

    def set_card_ttl(self, seconds: float):
        self._win.set_card_ttl(seconds)

    def add_trace(self, kind: str, msg: str) -> None:
        self._win.add_trace(kind, msg)

    def clear_trace(self) -> None:
        self._win.clear_trace()

    def set_show_trace(self, show: bool) -> None:
        self._win.set_show_trace(show)

    def toggle_trace_collapsed(self) -> None:
        self._win.toggle_trace_collapsed()

    def add_recall(self, query: str, fact: str) -> None:
        self._win.add_recall(query, fact)

    def clear_recalls(self) -> None:
        self._win.clear_recalls()


