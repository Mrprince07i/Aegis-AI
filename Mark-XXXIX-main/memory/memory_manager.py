import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"

    return result + "\n"

def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ==================== Recall Memory (semantic-ish local search) ====================
# Pure-Python fuzzy recall over long_term.json — no embeddings, no network.
# Combines: exact-substring, sub-token (with per-word fuzzy tolerance),
# Jaccard word overlap, and SequenceMatcher ratio. Returns a ranked list.
_VALID_CATS = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
_LIST_ALL_QUERIES = {"", "all", "everything", "list", "show all", "what do you know",
                     "what do you remember", "memories", "list all"}


def _word_tokens(text: str) -> set:
    """Lowercase word tokens, stripping punctuation. Filters out single-char
    tokens and common stopwords (English + Hindi) to avoid noisy matches."""
    if not text:
        return set()
    raw = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    stop = {
        "a", "an", "the", "i", "in", "on", "at", "to", "of", "is", "it", "or",
        "and", "be", "as", "by", "for", "if", "my", "me", "we", "he", "she",
        "है", "मैं", "मेरा", "मेरी", "के", "की", "को", "से", "और", "हूं",
    }
    return {w for w in raw if len(w) >= 2 and w not in stop}


def _word_similar(q_word: str, t_words: set, threshold: float = 0.78) -> bool:
    """q_word matches if it appears as a substring of a t_word (e.g. 'age' in
    'language'), or is fuzzy-similar (handles typos like 'piza' ~ 'pizza').
    Skips single-char t_words to avoid 'a' matching every query."""
    for t_word in t_words:
        if not t_word or len(t_word) < 2:
            continue
        # q_word is substring of t_word
        if len(q_word) >= 2 and q_word in t_word:
            return True
        # Fuzzy match (both must be at least 3 chars to be meaningful)
        if len(q_word) >= 3 and len(t_word) >= 3:
            if SequenceMatcher(None, q_word, t_word).ratio() >= threshold:
                return True
    return False


def _score_match(query: str, text: str) -> float:
    """
    Score 0-1: how well `query` matches `text`.
    Highest weight to sub-token (per-word substring/fuzzy) hits,
    then Jaccard overlap, then full SequenceMatcher ratio.
    """
    if not query or not text:
        return 0.0
    q = query.lower().strip()
    t = text.lower().strip()
    if not q or not t:
        return 0.0

    # 1. Exact substring — fastest, highest confidence
    if q in t:
        return 1.0

    q_words = _word_tokens(q)
    t_words = _word_tokens(t)
    if not q_words:
        return 0.0

    # 2. Sub-token coverage (per-word substring + fuzzy tolerance)
    if t_words:
        hits = sum(1 for w in q_words if w in t or _word_similar(w, t_words))
        sub_token = hits / len(q_words)
    else:
        sub_token = 0.0

    # 3. Jaccard word overlap
    if t_words:
        overlap = len(q_words & t_words) / len(q_words | t_words)
    else:
        overlap = 0.0

    # 4. Full-string fuzzy (helps with typos in short queries only).
    #    Penalize by length ratio so "birthday" (9 chars) doesn't get inflated
    #    scores against short values like "city india" (10 chars).
    fuzzy = 0.0
    if q and t and len(q) <= 12:
        raw = SequenceMatcher(None, q, t).ratio()
        len_ratio = min(len(q), len(t)) / max(len(q), len(t))
        fuzzy = raw * len_ratio

    return max(0.95 * sub_token, overlap, 0.7 * fuzzy)


def _format_recall(query: str, results: list, total: int, limit: int) -> str:
    if not results:
        all_count = sum(len(c) for c in load_memory().values() if isinstance(c, dict))
        if query.strip().lower() in _LIST_ALL_QUERIES:
            return f"No memories stored yet. ({all_count} total entries on file.)"
        return f"No memory found matching '{query}'. ({all_count} total entries on file.)"
    lines = [f"📂 Recalled {len(results)} memory(ies) for '{query}':"]
    for r in results:
        v = r["value"]
        if len(v) > 140:
            v = v[:137] + "…"
        score_pct = int(r["score"] * 100)
        lines.append(
            f"  • [{r['category']}/{r['key']}]  ({score_pct}% match, saved {r['updated']})\n"
            f"      → {v}"
        )
    return "\n".join(lines)


def recall_memory(query: str, category: str | None = None, limit: int = 3) -> str:
    """
    Search long-term memory for facts matching `query`.
    Returns a formatted, ranked string the LLM can quote directly.

    Strict by default: only returns high-confidence matches so the assistant
    doesn't accidentally surface unrelated memories. Use empty query or
    'all' to list everything on file.

    Args:
        query:    Search string. Use '' / 'all' to list all memories.
        category: Optional filter: identity | preferences | projects |
                  relationships | wishes | notes
        limit:    Max results to return (default 3).
    """
    try:
        limit = max(1, min(20, int(limit)))
    except Exception:
        limit = 3

    memory   = load_memory()
    q_clean  = (query or "").strip().lower()

    # Pick the categories to search
    if category and category in _VALID_CATS:
        cats_to_search = {category: memory.get(category, {})}
    else:
        cats_to_search = {
            c: memory.get(c, {})
            for c in _VALID_CATS
            if isinstance(memory.get(c), dict)
        }

    # ── "list all" mode ──
    if q_clean in _LIST_ALL_QUERIES:
        all_entries = []
        for cat, items in cats_to_search.items():
            for key, entry in items.items():
                if isinstance(entry, dict) and "value" in entry:
                    all_entries.append({
                        "category": cat, "key": key,
                        "value":   str(entry.get("value", "")),
                        "updated": str(entry.get("updated", "")),
                        "score":   1.0,
                    })
        # Newest first
        all_entries.sort(key=lambda x: x["updated"], reverse=True)
        # In "list all" mode, default to a high cap so the LLM gets everything
        effective_limit = max(limit, 20)
        return _format_recall(query or "all", all_entries[:effective_limit],
                              total=len(all_entries), limit=effective_limit)

    # ── Scored search (strict) ──
    scored = []
    for cat, items in cats_to_search.items():
        for key, entry in items.items():
            if not isinstance(entry, dict) or "value" not in entry:
                continue
            value = str(entry.get("value", ""))
            # Score against key (humanized) + value
            combined = f"{key.replace('_', ' ')} {value}"
            s = _score_match(q_clean, combined)
            # Strict inclusion: score >= 0.55 (was 0.30) so only confident
            # matches surface. Reduces false positives dramatically.
            if s >= 0.55:
                scored.append({
                    "category": cat, "key": key, "value": value,
                    "updated": str(entry.get("updated", "")),
                    "score":   round(s, 3),
                })

    scored.sort(key=lambda x: -x["score"])
    return _format_recall(query, scored[:limit], total=len(scored), limit=limit)