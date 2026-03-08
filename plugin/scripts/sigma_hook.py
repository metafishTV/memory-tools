#!/usr/bin/env python3
"""
Session Buffer — Sigma Hook (UserPromptSubmit)

Fires on every user message. Cascades through sigma layers:

  message → hot layer → concept digest → alpha (if needed)

Each level is cheaper than the next. Most messages during active work
match hot context and never touch alpha. Alpha dip is the "deep reach"
reserved for when the user references concepts outside current work.

Output format (ultra-minimal):
  σ hot: thread[2] "R&B deep review" [noted]
  σ w:62 alterity (Levinas)
  σ w:73 rhizomatic | w:74 arborescent (DG)

Design constraints:
  - Max 3 entries injected total (across all cascade levels)
  - Max 15 keywords extracted from message
  - Total injection < ~100 tokens
  - Must complete in <5s
  - Hot layer: ~0ms (tiny JSON, already in memory)
  - Alpha: ~10ms (3000-line index scan, only if hot misses)
"""

import sys
import os
import io
import json
import re

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_INJECT = 3        # max entries to inject (total across all levels)
MAX_KEYWORDS = 15     # max keywords extracted from message
MIN_WORD_LEN = 4      # skip short words
SCORE_EXACT = 3       # exact match weight
SCORE_SUBSTRING = 1   # substring match weight
MIN_SCORE = 2         # minimum score to qualify for alpha

# Common words to skip
STOPWORDS = frozenset({
    'this', 'that', 'what', 'which', 'where', 'when', 'with', 'from',
    'have', 'been', 'will', 'would', 'could', 'should', 'about', 'their',
    'there', 'these', 'those', 'then', 'than', 'them', 'they', 'some',
    'into', 'also', 'just', 'like', 'make', 'made', 'does', 'doing',
    'done', 'much', 'many', 'more', 'most', 'such', 'very', 'each',
    'both', 'same', 'other', 'only', 'well', 'back', 'over', 'here',
    'after', 'before', 'being', 'still', 'first', 'last', 'even',
    'want', 'need', 'know', 'think', 'look', 'find', 'give', 'tell',
    'take', 'come', 'keep', 'help', 'show', 'turn', 'work', 'call',
    'going', 'thing', 'right', 'good', 'long', 'great', 'little',
    'file', 'code', 'read', 'write', 'edit', 'commit', 'push', 'pull',
    'test', 'build', 'sure', 'okay', 'yeah', 'please', 'thanks',
    'can', 'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
})


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def find_buffer_dir(start_path):
    """Walk up from start_path looking for .claude/buffer/handoff.json."""
    current = os.path.abspath(start_path)
    while True:
        candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
        if os.path.exists(candidate):
            return os.path.join(current, '.claude', 'buffer')
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def read_json(path):
    """Read JSON file, return dict or None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_hook_input():
    """Read hook input JSON from stdin."""
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            return json.loads(stdin_data)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def emit(output):
    """Write JSON output and exit."""
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.exit(0)


def emit_empty():
    """No match — silent exit."""
    emit({})


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def extract_keywords(text):
    """Extract meaningful keywords from user message.

    Returns list of lowercase keywords, max MAX_KEYWORDS.
    Preserves underscore_joined terms (likely concept names).
    """
    if not text:
        return []

    # Find underscore_joined terms first (high signal)
    underscore_terms = re.findall(r'[a-zA-Z]+(?:_[a-zA-Z]+)+', text)
    underscore_lower = [t.lower() for t in underscore_terms]

    # Split into words
    cleaned = text.lower()
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    words = cleaned.split()

    keywords = []
    seen = set()

    for term in underscore_lower:
        if term not in seen:
            keywords.append(term)
            seen.add(term)

    for w in words:
        if (len(w) >= MIN_WORD_LEN
                and w not in STOPWORDS
                and w not in seen
                and w.isalpha()):
            keywords.append(w)
            seen.add(w)

    return keywords[:MAX_KEYWORDS]


# ---------------------------------------------------------------------------
# CASCADE LEVEL 1: Hot layer matching
# ---------------------------------------------------------------------------

def word_match(keyword, text_lower):
    """Check if keyword appears as a whole word in text (not as substring of another word)."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text_lower))


def match_hot(keywords, hot):
    """Match keywords against hot layer fields.

    Checks: active_work, open_threads, recent_decisions, orientation.why_keys.
    Uses word-boundary matching to avoid false positives (e.g. "concept" in "reconception").
    Returns list of (label, text) hits, max MAX_INJECT.
    """
    if not keywords or not hot:
        return []

    hits = []

    # --- active_work fields ---
    aw = hot.get('active_work', {})
    for field in ('current_phase', 'in_progress', 'next_action'):
        val = aw.get(field)
        if val and isinstance(val, str) and val != 'None':
            val_lower = val.lower()
            for kw in keywords:
                if word_match(kw, val_lower):
                    hits.append(('active', f"{field}: {val}"))
                    break

    # --- open_threads ---
    threads = hot.get('open_threads', [])
    for i, t in enumerate(threads):
        thread_text = t.get('thread', '')
        status = t.get('status', '?')
        if thread_text:
            thread_lower = thread_text.lower()
            for kw in keywords:
                if word_match(kw, thread_lower):
                    hits.append(('thread', f"[{status}] {thread_text}"))
                    break

    # --- recent_decisions ---
    decisions = hot.get('recent_decisions', [])
    for d in decisions:
        what = d.get('what', '')
        chose = d.get('chose', '')
        combined = f"{what} {chose}".lower()
        for kw in keywords:
            if word_match(kw, combined):
                hits.append(('decision', f"{what} -> {chose}"))
                break

    # --- orientation.why_keys (source names — exact or close match ok) ---
    why_keys = hot.get('orientation', {}).get('why_keys', [])
    matched_sources = []
    for wk in why_keys:
        wk_lower = wk.lower()
        for kw in keywords:
            if kw == wk_lower or kw in wk_lower or wk_lower in kw:
                matched_sources.append(wk)
                break
    if matched_sources:
        hits.append(('source', ', '.join(matched_sources)))

    return hits[:MAX_INJECT]


def format_hot_hits(hits):
    """Format hot layer hits into minimal injection string.

    Format: sigma hot: thread[noted] "R&B deep review" | active: next_action: ...
    """
    parts = []
    for label, text in hits:
        # Truncate long text
        if len(text) > 60:
            text = text[:57] + '...'
        parts.append(f"{label}: {text}")

    return 'sigma hot: ' + ' | '.join(parts)


# ---------------------------------------------------------------------------
# CASCADE LEVEL 2: Alpha concept matching (fallthrough)
# ---------------------------------------------------------------------------

def match_alpha_concepts(keywords, concept_index):
    """Match keywords against alpha concept_index keys.

    Returns list of (concept_key, work_ids, score) sorted by score desc.
    """
    if not keywords or not concept_index:
        return []

    scores = {}

    for concept_key, work_ids in concept_index.items():
        if concept_key == '?':
            continue

        concept_lower = concept_key.lower()
        score = 0

        for kw in keywords:
            if kw == concept_lower:
                score += SCORE_EXACT
            elif kw in concept_lower or concept_lower in kw:
                score += SCORE_SUBSTRING

        if score >= MIN_SCORE:
            scores[concept_key] = (work_ids, score)

    ranked = sorted(scores.items(), key=lambda x: x[1][1], reverse=True)
    return [(key, ids, sc) for key, (ids, sc) in ranked[:MAX_INJECT]]


def find_source_for_id(work_id, sources_data):
    """Find which source a work ID belongs to. Returns source name or None."""
    if not sources_data:
        return None

    for source_key, source_info in sources_data.items():
        if not isinstance(source_info, dict):
            continue
        for id_list_key in ('cross_source_ids', 'convergence_web_ids'):
            id_list = source_info.get(id_list_key, [])
            if work_id in id_list:
                return source_key
    return None


def format_alpha_hits(concept_matches, sources_data):
    """Format alpha concept matches into minimal injection string.

    Format: sigma alpha: w:62 alterity (Levinas) | w:73 rhizomatic (DG)
    """
    parts = []

    for concept_key, work_ids, score in concept_matches:
        wid = work_ids[0] if isinstance(work_ids, list) and work_ids else '?'
        source = find_source_for_id(wid, sources_data)
        if source:
            parts.append(f"{wid} {concept_key} ({source})")
        else:
            parts.append(f"{wid} {concept_key}")

    return 'sigma alpha: ' + ' | '.join(parts)


# ---------------------------------------------------------------------------
# Main — cascade logic
# ---------------------------------------------------------------------------

def main():
    hook_input = read_hook_input()
    user_prompt = hook_input.get('user_prompt', '')
    cwd = hook_input.get('cwd', os.getcwd())

    # Quick exits
    if not user_prompt or len(user_prompt.strip()) < 8:
        emit_empty()
    if user_prompt.strip().startswith('/'):
        emit_empty()

    # Find buffer
    buffer_dir = find_buffer_dir(cwd)
    if not buffer_dir:
        emit_empty()

    # Extract keywords
    keywords = extract_keywords(user_prompt)
    if not keywords:
        emit_empty()

    # -----------------------------------------------------------------------
    # LEVEL 1: Hot layer check (cheapest)
    # -----------------------------------------------------------------------
    hot = read_json(os.path.join(buffer_dir, 'handoff.json'))
    if hot:
        hot_hits = match_hot(keywords, hot)
        if hot_hits:
            injection = format_hot_hits(hot_hits)
            emit({"suppressOutput": True, "systemMessage": injection})

    # -----------------------------------------------------------------------
    # LEVEL 2: Alpha concept index (fallthrough — hot didn't match)
    # -----------------------------------------------------------------------
    alpha_path = os.path.join(buffer_dir, 'alpha', 'index.json')
    alpha_idx = read_json(alpha_path)
    if not alpha_idx:
        emit_empty()

    concept_index = alpha_idx.get('concept_index', {})
    sources_data = alpha_idx.get('sources', {})

    concept_matches = match_alpha_concepts(keywords, concept_index)
    if not concept_matches:
        emit_empty()

    injection = format_alpha_hits(concept_matches, sources_data)
    emit({"suppressOutput": True, "systemMessage": injection})


if __name__ == '__main__':
    main()
