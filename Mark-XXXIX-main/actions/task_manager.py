"""
task_manager.py
---------------
JARVIS task / todo system.
Tasks are saved as JSON in memory/tasks/tasks.json.  Each task has
an id, text, done flag, priority, optional due date and timestamps.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


# ── Storage ───────────────────────────────────────────────────────────────────
def _base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_TASKS_DIR = _base() / "memory" / "tasks"
_TASKS_DIR.mkdir(parents=True, exist_ok=True)
TASKS_FILE = _TASKS_DIR / "tasks.json"


def _load() -> list[dict]:
    try:
        if TASKS_FILE.exists():
            return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save(tasks: list[dict]) -> None:
    TASKS_FILE.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Priority helpers ──────────────────────────────────────────────────────────
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
PRIORITY_COLOR = {
    "high":   ("#ff3355", "#1a0008"),
    "medium": ("#ffb347", "#1a1100"),
    "low":    ("#7fc8ff", "#001a22"),
}
PRIORITY_LABEL = {"high": "HIGH", "medium": "MED", "low": "LOW"}


def _detect_priority(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["urgent", "asap", "jaldi", "turant", "important", "zaroor"]):
        return "high"
    if any(w in t for w in ["baad", "later", "kal", "tomorrow", "someday", "jab time"]):
        return "low"
    return "medium"


# ── Public API ────────────────────────────────────────────────────────────────
def add_task(text: str, priority: str | None = None, due: str | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Task text cannot be empty")
    if priority not in PRIORITY_ORDER:
        priority = _detect_priority(text)
    tasks = _load()
    new_id = max([t.get("id", 0) for t in tasks], default=0) + 1
    task = {
        "id":         new_id,
        "text":       text,
        "done":       False,
        "priority":   priority,
        "due":        due,
        "created":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "completed":  None,
    }
    tasks.append(task)
    _save(tasks)
    return task


def complete_task(task_id: int, done: bool = True) -> dict | None:
    tasks = _load()
    for t in tasks:
        if t.get("id") == task_id:
            t["done"] = bool(done)
            t["completed"] = datetime.now().strftime("%Y-%m-%d %H:%M") if done else None
            _save(tasks)
            return t
    return None


def delete_task(task_id: int) -> bool:
    tasks = _load()
    new = [t for t in tasks if t.get("id") != task_id]
    if len(new) == len(tasks):
        return False
    _save(new)
    return True


def clear_done() -> int:
    tasks = _load()
    before = len(tasks)
    tasks = [t for t in tasks if not t.get("done")]
    _save(tasks)
    return before - len(tasks)


def list_tasks(include_done: bool = True) -> list[dict]:
    tasks = _load()
    if not include_done:
        tasks = [t for t in tasks if not t.get("done")]
    return sorted(
        tasks,
        key=lambda t: (
            t.get("done", False),
            PRIORITY_ORDER.get(t.get("priority", "medium"), 1),
            -(int(t.get("created", "1970-01-01 00:00").replace("-", "").replace(":", "").replace(" ", ""))),
        ),
    )


# ── Tool entry (called from main.py / AI dispatcher) ─────────────────────────
def task_manager(parameters: dict, player=None) -> str:
    action = parameters.get("action", "list").lower()
    if action in ("add", "create", "new"):
        text     = parameters.get("text", parameters.get("title", "")).strip()
        priority = parameters.get("priority")
        due      = parameters.get("due")
        if not text:
            return "Task text is required."
        t = add_task(text, priority, due)
        if player:
            player.write_log(f"SYS: Task added - {t['text']} [{t['priority'].upper()}]")
        return f"Task #{t['id']} added: '{t['text']}' [{t['priority'].upper()}]"

    if action in ("complete", "done", "check"):
        try:
            tid = int(parameters.get("id", 0))
        except (TypeError, ValueError):
            return "Invalid task id."
        t = complete_task(tid, True)
        if t is None:
            return f"Task #{tid} not found."
        if player:
            player.write_log(f"SYS: Task #{tid} marked done - {t['text']}")
        return f"Task #{tid} marked done."

    if action in ("delete", "remove"):
        try:
            tid = int(parameters.get("id", 0))
        except (TypeError, ValueError):
            return "Invalid task id."
        if delete_task(tid):
            if player:
                player.write_log(f"SYS: Task #{tid} removed")
            return f"Task #{tid} removed."
        return f"Task #{tid} not found."

    if action == "list":
        tasks = list_tasks(include_done=True)
        if not tasks:
            return "No tasks yet."
        lines = []
        for t in tasks:
            mark = "[x]" if t.get("done") else "[ ]"
            lines.append(
                f"{mark} #{t['id']} [{t['priority'].upper()}] {t['text']} - {t.get('created','')}"
            )
        return "Tasks:\n" + "\n".join(lines)

    if action == "clear":
        n = clear_done()
        return f"Cleared {n} completed task(s)."

    return "Unknown action. Use: add, complete, delete, list, clear."
