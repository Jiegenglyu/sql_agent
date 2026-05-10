from __future__ import annotations

from pathlib import Path
import re
from typing import Any


class BusinessRuleError(ValueError):
    """Raised when a business rule path or query violates policy."""


ALLOWED_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json"}
MAX_QUERY_LENGTH = 500
DEFAULT_MAX_FILE_BYTES = 256_000
DEFAULT_MAX_RESULTS = 8


def search_rules(
    query: str,
    *,
    base_dir: Path | None = None,
    limit: int | None = None,
    max_file_bytes: int | None = None,
) -> list[dict[str, Any]]:
    base = _rules_base(base_dir)
    query_text = query.strip()
    if not query_text:
        return []
    if len(query_text) > MAX_QUERY_LENGTH:
        raise BusinessRuleError("Rule search query is too long.")

    result_limit = min(limit or _default_max_results(), 50)
    max_bytes = max_file_bytes or _default_max_file_bytes()
    terms = _tokens(query_text)

    matches: list[dict[str, Any]] = []
    for path in _iter_rule_files(base, max_bytes=max_bytes):
        text = path.read_text(encoding="utf-8", errors="replace")
        score, snippets = _score_text(text, path.relative_to(base).as_posix(), terms)
        if score <= 0:
            continue
        matches.append(
            {
                "path": path.relative_to(base).as_posix(),
                "score": score,
                "snippets": snippets[:3],
            }
        )

    matches.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return matches[:result_limit]


def read_rule(
    relative_path: str,
    *,
    base_dir: Path | None = None,
    max_file_bytes: int | None = None,
) -> dict[str, Any]:
    base = _rules_base(base_dir)
    max_bytes = max_file_bytes or _default_max_file_bytes()
    path = _safe_rule_path(base, relative_path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise BusinessRuleError("Rule file extension is not allowed.")
    if path.stat().st_size > max_bytes:
        raise BusinessRuleError("Rule file exceeds the maximum allowed size.")
    return {
        "path": path.relative_to(base).as_posix(),
        "content": path.read_text(encoding="utf-8", errors="replace"),
    }


def list_rule_files(*, base_dir: Path | None = None) -> list[str]:
    base = _rules_base(base_dir)
    return [path.relative_to(base).as_posix() for path in _iter_rule_files(base)]


def _rules_base(base_dir: Path | None) -> Path:
    if base_dir is None:
        base_dir = _settings().business_rules_dir
    base = base_dir.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _settings():
    from backend.app.config import get_settings

    return get_settings()


def _default_max_file_bytes() -> int:
    try:
        return int(_settings().business_rule_max_file_bytes)
    except ModuleNotFoundError:
        return DEFAULT_MAX_FILE_BYTES


def _default_max_results() -> int:
    try:
        return int(_settings().business_rule_max_results)
    except ModuleNotFoundError:
        return DEFAULT_MAX_RESULTS


def _safe_rule_path(base: Path, relative_path: str) -> Path:
    if not relative_path or len(relative_path) > 300:
        raise BusinessRuleError("Invalid rule path.")
    raw = Path(relative_path)
    if raw.is_absolute():
        raise BusinessRuleError("Absolute rule paths are not allowed.")
    path = (base / raw).resolve()
    if not path.is_relative_to(base):
        raise BusinessRuleError("Rule path escapes the business rules directory.")
    if path.is_symlink():
        raise BusinessRuleError("Symlinked rule files are not allowed.")
    if not path.is_file():
        raise BusinessRuleError("Rule file was not found.")
    return path


def _iter_rule_files(base: Path, *, max_bytes: int | None = None) -> list[Path]:
    files: list[Path] = []
    for path in base.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(base):
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if max_bytes is not None and path.stat().st_size > max_bytes:
            continue
        files.append(resolved)
    files.sort()
    return files


def _tokens(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()):
        candidates = [raw]
        if re.search(r"[\u4e00-\u9fff]", raw):
            candidates.extend(_cjk_ngrams(raw, sizes=(2, 3)))
        for candidate in candidates:
            if len(candidate) < 2 or candidate in seen:
                continue
            terms.append(candidate)
            seen.add(candidate)
    return terms[:40]


def _cjk_ngrams(text: str, *, sizes: tuple[int, ...]) -> list[str]:
    chars = [char for char in text if re.match(r"[\u4e00-\u9fff]", char)]
    grams: list[str] = []
    for size in sizes:
        if len(chars) < size:
            continue
        grams.extend("".join(chars[index : index + size]) for index in range(len(chars) - size + 1))
    return grams


def _score_text(text: str, relative_path: str, terms: list[str]) -> tuple[int, list[dict[str, Any]]]:
    lower_text = text.lower()
    lower_path = relative_path.lower()
    score = 0
    for term in terms:
        score += lower_path.count(term) * 5
        score += lower_text.count(term)

    snippets: list[dict[str, Any]] = []
    if score <= 0:
        return 0, snippets

    for line_no, line in enumerate(text.splitlines(), start=1):
        lower_line = line.lower()
        if any(term in lower_line for term in terms):
            snippets.append(
                {
                    "line": line_no,
                    "text": line.strip()[:500],
                }
            )
        if len(snippets) >= 3:
            break
    return score, snippets
