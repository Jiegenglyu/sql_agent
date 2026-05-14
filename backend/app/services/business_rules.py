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
DEFAULT_READ_CONTEXT_LINES = 24
MAX_READ_LINES = 200
DEFAULT_CONFIDENCE_THRESHOLD = 0.62
DEFAULT_AMBIGUITY_MARGIN = 0.18
DEFAULT_TABLE_LIMIT = 3

FIXED_MARKER_TERMS = ("固定", "公共", "默认", "mandatory", "common", "always", "fixed")
BUSINESS_MARKER_TERMS = ("业务", "指标", "metric", "business", "logic", "rule")
METADATA_KEYS = {"schema", "table", "aliases", "alias", "keywords", "related_tables", "related", "join_tables"}
DIMENSION_TABLE_HINTS: dict[str, tuple[str, ...]] = {
    "teams": ("团队", "team", "owner", "business unit", "业务线"),
    "clusters": ("集群", "cluster", "region", "区域", "provider"),
    "workloads": ("工作负载", "workload", "任务", "作业", "job"),
    "gpu_nodes": ("节点", "node", "机器", "主机", "gpu node", "npu node"),
}
GENERIC_QUERY_TERMS = ("使用情况", "情况", "概况", "查一下", "看一下", "usage", "status", "overview")
SPECIFIC_QUERY_TERMS = (
    "卡时",
    "核心",
    "利用率",
    "成本",
    "单卡",
    "告警",
    "事件",
    "总卡",
    "容量压力",
    "队列",
)


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
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    base = _rules_base(base_dir)
    max_bytes = max_file_bytes or _default_max_file_bytes()
    path = _safe_rule_path(base, relative_path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise BusinessRuleError("Rule file extension is not allowed.")
    if path.stat().st_size > max_bytes:
        raise BusinessRuleError("Rule file exceeds the maximum allowed size.")
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    selected_start, selected_end, truncated = _resolve_line_range(
        len(lines),
        start_line=start_line,
        end_line=end_line,
    )
    selected_lines = lines[selected_start - 1 : selected_end] if selected_start else []
    return {
        "path": path.relative_to(base).as_posix(),
        "content": "\n".join(selected_lines) if selected_lines else "",
        "start_line": selected_start,
        "end_line": selected_end,
        "line_count": len(lines),
        "truncated": truncated,
        "snippets": _line_snippets(selected_lines, selected_start),
    }


def list_rule_files(*, base_dir: Path | None = None) -> list[str]:
    base = _rules_base(base_dir)
    return [path.relative_to(base).as_posix() for path in _iter_rule_files(base)]


def resolve_business_rules(
    query: str,
    *,
    base_dir: Path | None = None,
    limit: int | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
    max_file_bytes: int | None = None,
) -> dict[str, Any]:
    """Resolve the minimum business-rule context needed for a user question.

    The resolver is intentionally table-first: structured rule files are mapped
    to tables, fixed logic is always carried for selected tables, and only
    matched business sections are returned.
    """
    base = _rules_base(base_dir)
    query_text = query.strip()
    if not query_text:
        return _empty_resolve_result(query_text, reason="empty_query")
    if len(query_text) > MAX_QUERY_LENGTH:
        raise BusinessRuleError("Rule resolve query is too long.")

    docs = _structured_rule_docs(base, max_file_bytes=max_file_bytes or _default_max_file_bytes())
    if not docs:
        return _empty_resolve_result(query_text, reason="no_structured_rules")

    terms = _tokens(query_text)
    raw_candidates = [_score_rule_doc(doc, terms, query_text) for doc in docs]
    candidates = [candidate for candidate in raw_candidates if candidate["score"] > 0]
    candidates.sort(key=lambda item: (-int(item["score"]), str(item["path"])))

    result_limit = min(limit or DEFAULT_TABLE_LIMIT, 10)
    top_candidates = candidates[:result_limit]
    confidence = _route_confidence(top_candidates)
    clarification_required = _needs_clarification(
        top_candidates,
        query_text=query_text,
        confidence=confidence,
        threshold=confidence_threshold,
        ambiguity_margin=ambiguity_margin,
    )
    selected_candidates = [] if clarification_required else _selected_candidates(top_candidates)
    selected_tables = _selected_tables(selected_candidates, query_text=query_text)

    return {
        "query": query_text,
        "structured_rule_count": len(docs),
        "candidate_count": len(candidates),
        "confidence": confidence,
        "confidence_threshold": confidence_threshold,
        "clarification_required": clarification_required,
        "reason": _resolve_reason(
            top_candidates,
            confidence=confidence,
            threshold=confidence_threshold,
            clarification_required=clarification_required,
        ),
        "candidates": top_candidates,
        "selected_tables": selected_tables,
        "options": _clarification_options(top_candidates or raw_candidates[:result_limit], query_text=query_text),
    }


def _empty_resolve_result(query: str, *, reason: str) -> dict[str, Any]:
    return {
        "query": query,
        "structured_rule_count": 0,
        "candidate_count": 0,
        "confidence": 0.0,
        "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
        "clarification_required": False,
        "reason": reason,
        "candidates": [],
        "selected_tables": [],
        "options": [],
    }


def _structured_rule_docs(base: Path, *, max_file_bytes: int) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in _iter_rule_files(base, max_bytes=max_file_bytes):
        if path.name.lower() == "readme.md":
            continue
        try:
            doc = _parse_rule_doc(path, base)
        except OSError:
            continue
        if not _is_structured_rule_doc(doc):
            continue
        docs.append(doc)
    docs.sort(key=lambda item: str(item["path"]))
    return docs


def _is_structured_rule_doc(doc: dict[str, Any]) -> bool:
    return bool(doc.get("fixed_logic") or doc.get("business_sections") or doc.get("explicit_table"))


def _parse_rule_doc(path: Path, base: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    metadata = _parse_rule_metadata(_metadata_lines(lines))
    fixed_range, business_range = _rule_ranges(lines)
    fixed_logic = _slice_lines(lines, fixed_range).strip()
    business_lines = _slice_lines(lines, business_range)
    sections = _parse_business_sections(business_lines, start_line=(business_range[0] if business_range else 1))
    relative_path = path.relative_to(base).as_posix()
    schema = _first_metadata_value(metadata, "schema")
    table = _first_metadata_value(metadata, "table")
    explicit_table = bool(table)
    if not table:
        table = path.stem
    if not schema and path.parent != base:
        schema = path.parent.relative_to(base).parts[0]

    aliases = _metadata_list(metadata, "aliases", "alias", "keywords")
    related_tables = _metadata_list(metadata, "related_tables", "related", "join_tables")
    title = _first_heading(lines) or table

    return {
        "path": relative_path,
        "schema": schema,
        "table": table,
        "title": title,
        "aliases": aliases,
        "related_tables": related_tables,
        "fixed_logic": fixed_logic,
        "business_sections": sections,
        "line_count": len(lines),
        "explicit_table": explicit_table,
    }


def _metadata_lines(lines: list[str]) -> list[str]:
    selected: list[str] = []
    for line in lines:
        if _marker_label(line):
            break
        selected.append(line)
    return selected


def _parse_rule_metadata(lines: list[str]) -> dict[str, list[str]]:
    metadata: dict[str, list[str]] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(?:[-*]\s*)?([A-Za-z_][\w-]*|别名|关键词|相关表)\s*[:：]\s*(.+)$", stripped)
        if not match:
            continue
        key = _metadata_key(match.group(1))
        if key not in METADATA_KEYS:
            continue
        metadata.setdefault(key, []).append(match.group(2).strip())
    return metadata


def _metadata_key(raw_key: str) -> str:
    key = raw_key.strip().lower().replace("-", "_")
    aliases = {
        "别名": "aliases",
        "关键词": "keywords",
        "相关表": "related_tables",
    }
    return aliases.get(key, key)


def _first_metadata_value(metadata: dict[str, list[str]], key: str) -> str | None:
    values = metadata.get(key) or []
    for value in values:
        clean = value.strip().strip("`")
        if clean:
            return clean
    return None


def _metadata_list(metadata: dict[str, list[str]], *keys: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for value in metadata.get(key) or []:
            for item in re.split(r"[,，、;\n]+", value):
                clean = item.strip().strip("`")
                if not clean or clean in seen:
                    continue
                items.append(clean)
                seen.add(clean)
    return items


def _rule_ranges(lines: list[str]) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    markers: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        label = _marker_label(line)
        if label:
            markers.append((index, label))

    fixed_start: int | None = None
    fixed_end: int | None = None
    business_start: int | None = None
    business_end: int | None = None
    for marker_index, (line_no, label) in enumerate(markers):
        lower_label = label.lower()
        next_line = markers[marker_index + 1][0] if marker_index + 1 < len(markers) else len(lines) + 1
        if fixed_start is None and any(term in lower_label for term in FIXED_MARKER_TERMS):
            fixed_start = line_no + 1
            fixed_end = next_line - 1
        if business_start is None and any(term in lower_label for term in BUSINESS_MARKER_TERMS):
            business_start = line_no + 1
            business_end = next_line - 1

    if business_start is None and fixed_end is not None and fixed_end < len(lines):
        business_start = fixed_end + 1
        business_end = len(lines)
    return _normalized_range(fixed_start, fixed_end), _normalized_range(business_start, business_end)


def _marker_label(line: str) -> str | None:
    match = re.match(r"^\s*###\s*(.*?)\s*###\s*$", line)
    if not match:
        return None
    return match.group(1).strip()


def _normalized_range(start: int | None, end: int | None) -> tuple[int, int] | None:
    if start is None or end is None or end < start:
        return None
    return (start, end)


def _slice_lines(lines: list[str], selected_range: tuple[int, int] | None) -> str:
    if selected_range is None:
        return ""
    start, end = selected_range
    return "\n".join(lines[start - 1 : end])


def _parse_business_sections(text: str, *, start_line: int) -> list[dict[str, Any]]:
    lines = text.splitlines()
    heading_indexes: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if match and not line.strip().startswith("###"):
            heading_indexes.append((index, match.group(1).strip()))

    if not heading_indexes:
        content = text.strip()
        if not content:
            return []
        return [
            {
                "title": "业务逻辑",
                "keywords": [],
                "content": content,
                "start_line": start_line,
                "end_line": start_line + len(lines) - 1,
            }
        ]

    sections: list[dict[str, Any]] = []
    for position, (line_index, title) in enumerate(heading_indexes):
        next_index = heading_indexes[position + 1][0] if position + 1 < len(heading_indexes) else len(lines)
        section_lines = lines[line_index + 1 : next_index]
        content = "\n".join(section_lines).strip()
        sections.append(
            {
                "title": title,
                "keywords": _section_keywords(title, section_lines),
                "content": content,
                "start_line": start_line + line_index,
                "end_line": start_line + next_index - 1,
            }
        )
    return sections


def _section_keywords(title: str, lines: list[str]) -> list[str]:
    keywords = [title]
    seen = {title}
    for line in lines:
        match = re.match(r"^\s*(?:[-*]\s*)?(?:keywords|关键词)\s*[:：]\s*(.+)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        for item in re.split(r"[,，、;]+", match.group(1)):
            clean = item.strip().strip("`")
            if clean and clean not in seen:
                keywords.append(clean)
                seen.add(clean)
    return keywords


def _first_heading(lines: list[str]) -> str | None:
    for line in lines:
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _score_rule_doc(doc: dict[str, Any], terms: list[str], query_text: str) -> dict[str, Any]:
    table_text = " ".join(
        [
            str(doc.get("path") or ""),
            str(doc.get("schema") or ""),
            str(doc.get("table") or ""),
            str(doc.get("title") or ""),
            " ".join(str(item) for item in doc.get("aliases") or []),
        ]
    )
    table_score = _weighted_term_score(table_text, terms, weight=5)
    fixed_score = _weighted_term_score(str(doc.get("fixed_logic") or ""), terms, weight=1)
    section_matches = []
    for section in doc.get("business_sections") or []:
        section_score = _score_section(section, terms)
        if section_score <= 0:
            continue
        matched_terms = _matched_terms(
            " ".join(
                [
                    str(section.get("title") or ""),
                    " ".join(str(item) for item in section.get("keywords") or []),
                    str(section.get("content") or ""),
                ]
            ),
            terms,
        )
        section_matches.append(
            {
                "title": section.get("title"),
                "keywords": section.get("keywords") or [],
                "content": section.get("content") or "",
                "start_line": section.get("start_line"),
                "end_line": section.get("end_line"),
                "score": section_score,
                "matched_terms": matched_terms,
            }
        )

    section_matches.sort(key=lambda item: (-int(item["score"]), str(item["title"])))
    selected_section_matches = _selected_section_matches(section_matches)
    score = table_score + fixed_score + sum(int(item["score"]) for item in selected_section_matches)
    if not section_matches and _explicit_table_mention(doc, query_text):
        score += 12

    snippets = _candidate_snippets(doc, selected_section_matches)
    return {
        "path": doc.get("path"),
        "schema": doc.get("schema"),
        "table": doc.get("table"),
        "score": score,
        "table_score": table_score,
        "fixed_logic": doc.get("fixed_logic") or "",
        "matched_sections": selected_section_matches,
        "snippets": snippets,
        "aliases": doc.get("aliases") or [],
        "related_tables": doc.get("related_tables") or [],
        "line_count": doc.get("line_count"),
    }


def _selected_section_matches(section_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not section_matches:
        return []
    top_score = int(section_matches[0].get("score") or 0)
    threshold = max(6, int(top_score * 0.35))
    return [item for item in section_matches if int(item.get("score") or 0) >= threshold][:3]


def _score_section(section: dict[str, Any], terms: list[str]) -> int:
    title_score = _weighted_term_score(str(section.get("title") or ""), terms, weight=8)
    keyword_score = _weighted_term_score(" ".join(str(item) for item in section.get("keywords") or []), terms, weight=7)
    content_score = _weighted_term_score(str(section.get("content") or ""), terms, weight=2)
    return title_score + keyword_score + content_score


def _weighted_term_score(text: str, terms: list[str], *, weight: int) -> int:
    lower_text = text.lower()
    score = 0
    for term in terms:
        count = lower_text.count(term)
        if count:
            score += count * weight
    return score


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    lower_text = text.lower()
    return [term for term in terms if term in lower_text][:12]


def _explicit_table_mention(doc: dict[str, Any], query_text: str) -> bool:
    lower_query = query_text.lower()
    table = str(doc.get("table") or "").lower()
    path = str(doc.get("path") or "").lower()
    return bool(table and table in lower_query) or bool(path and path in lower_query)


def _candidate_snippets(doc: dict[str, Any], section_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for section in section_matches[:3]:
        line = section.get("start_line")
        text = str(section.get("title") or "")
        if line and text:
            snippets.append({"line": line, "text": text[:500]})
    if not snippets and doc.get("fixed_logic"):
        snippets.append({"line": 1, "text": "固定查询逻辑"})
    return snippets


def _route_confidence(candidates: list[dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    top_score = max(int(candidates[0].get("score") or 0), 0)
    second_score = max(int(candidates[1].get("score") or 0), 0) if len(candidates) > 1 else 0
    if top_score <= 0:
        return 0.0
    strength = min(top_score / 40.0, 1.0)
    separation = 1.0 if second_score <= 0 else max((top_score - second_score) / top_score, 0.0)
    confidence = 0.35 + 0.4 * strength + 0.25 * separation
    return round(min(confidence, 0.98), 3)


def _needs_clarification(
    candidates: list[dict[str, Any]],
    *,
    query_text: str,
    confidence: float,
    threshold: float,
    ambiguity_margin: float,
) -> bool:
    if not candidates:
        return True
    top_score = int(candidates[0].get("score") or 0)
    if top_score < 6:
        return True
    if confidence < threshold:
        return True
    if _has_ambiguous_sections(candidates[0], query_text=query_text):
        return True
    if len(candidates) < 2:
        return False
    second_score = int(candidates[1].get("score") or 0)
    if second_score <= 0:
        return False
    return (top_score - second_score) / max(top_score, 1) <= ambiguity_margin


def _has_ambiguous_sections(candidate: dict[str, Any], *, query_text: str) -> bool:
    lower_query = query_text.lower()
    if not any(term in lower_query for term in GENERIC_QUERY_TERMS):
        return False
    if any(term in lower_query for term in SPECIFIC_QUERY_TERMS):
        return False
    sections = candidate.get("matched_sections")
    if not isinstance(sections, list) or len(sections) < 2:
        return False
    top_score = int(sections[0].get("score") or 0)
    second_score = int(sections[1].get("score") or 0)
    return top_score > 0 and second_score / top_score >= 0.55


def _selected_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    top_score = int(candidates[0].get("score") or 0)
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        score = int(candidate.get("score") or 0)
        if candidate is candidates[0] or (score >= 10 and score >= top_score * 0.55):
            selected.append(candidate)
    return selected


def _selected_tables(candidates: list[dict[str, Any]], *, query_text: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()

    for candidate in candidates:
        _append_selected_table(
            selected,
            seen,
            schema=_clean_schema(candidate.get("schema")),
            table=str(candidate.get("table") or ""),
            role="primary",
            source_path=str(candidate.get("path") or ""),
            reason="business_rule_match",
        )
        for related in candidate.get("related_tables") or []:
            if not _related_table_is_relevant(str(related), query_text=query_text):
                continue
            schema, table = _split_table_reference(str(related), default_schema=_clean_schema(candidate.get("schema")))
            _append_selected_table(
                selected,
                seen,
                schema=schema,
                table=table,
                role="related",
                source_path=str(candidate.get("path") or ""),
                reason="rule_related_table",
            )

    for candidate in candidates:
        default_schema = _clean_schema(candidate.get("schema"))
        for table, hints in DIMENSION_TABLE_HINTS.items():
            if not any(hint.lower() in query_text.lower() for hint in hints):
                continue
            _append_selected_table(
                selected,
                seen,
                schema=default_schema,
                table=table,
                role="related",
                source_path=str(candidate.get("path") or ""),
                reason="question_dimension_hint",
            )

    return selected[:8]


def _related_table_is_relevant(value: str, *, query_text: str) -> bool:
    _, table = _split_table_reference(value, default_schema=None)
    lower_query = query_text.lower()
    if table and table.lower() in lower_query:
        return True
    hints = DIMENSION_TABLE_HINTS.get(table, ())
    return any(hint.lower() in lower_query for hint in hints)


def _append_selected_table(
    selected: list[dict[str, Any]],
    seen: set[tuple[str | None, str]],
    *,
    schema: str | None,
    table: str,
    role: str,
    source_path: str,
    reason: str,
) -> None:
    clean_table = table.strip().strip("`")
    if not clean_table:
        return
    key = (schema, clean_table)
    if key in seen:
        return
    selected.append(
        {
            "schema": schema,
            "table": clean_table,
            "role": role,
            "source_path": source_path,
            "reason": reason,
        }
    )
    seen.add(key)


def _split_table_reference(value: str, *, default_schema: str | None) -> tuple[str | None, str]:
    clean = value.strip().strip("`")
    if "." not in clean:
        return default_schema, clean
    schema, table = clean.split(".", 1)
    return schema.strip() or default_schema, table.strip()


def _clean_schema(value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).strip().strip("`")
    return clean or None


def _clarification_options(candidates: list[dict[str, Any]], *, query_text: str) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str, str]] = set()
    top_score = int(candidates[0].get("score") or 0) if candidates else 0
    min_score = max(6, int(top_score * 0.2)) if top_score else 0
    for candidate in candidates:
        if int(candidate.get("score") or 0) < min_score:
            continue
        schema = _clean_schema(candidate.get("schema"))
        table = str(candidate.get("table") or "")
        sections = candidate.get("matched_sections") or []
        if not sections:
            sections = [{"title": candidate.get("table") or candidate.get("path"), "content": "", "score": candidate.get("score", 0)}]
        for section in sections[:2]:
            title = str(section.get("title") or table)
            key = (schema, table, title)
            if key in seen:
                continue
            options.append(
                {
                    "label": title,
                    "table": _format_table(schema, table),
                    "path": candidate.get("path"),
                    "score": section.get("score", candidate.get("score", 0)),
                    "reason": _option_reason(section, query_text),
                }
            )
            seen.add(key)
            if len(options) >= 5:
                return options
    return options


def _option_reason(section: dict[str, Any], query_text: str) -> str:
    matched_terms = section.get("matched_terms")
    if isinstance(matched_terms, list) and matched_terms:
        return "matched: " + ", ".join(str(term) for term in matched_terms[:4])
    return f"possible meaning for: {query_text[:40]}"


def _format_table(schema: str | None, table: str) -> str:
    return f"{schema}.{table}" if schema else table


def _resolve_reason(
    candidates: list[dict[str, Any]],
    *,
    confidence: float,
    threshold: float,
    clarification_required: bool,
) -> str:
    if not candidates:
        return "no_candidate_rules"
    if clarification_required:
        if confidence < threshold:
            return "low_confidence"
        return "ambiguous_candidates"
    return "confident_match"


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


def _resolve_line_range(
    line_count: int,
    *,
    start_line: int | None,
    end_line: int | None,
) -> tuple[int, int, bool]:
    if line_count == 0:
        return 0, 0, False

    if start_line is None and end_line is None:
        return 1, line_count, False
    if start_line is not None and start_line < 1:
        raise BusinessRuleError("Rule start_line must be greater than zero.")
    if end_line is not None and end_line < 1:
        raise BusinessRuleError("Rule end_line must be greater than zero.")

    start = start_line or 1
    if start > line_count:
        raise BusinessRuleError("Rule start_line exceeds the file length.")

    end = end_line or min(line_count, start + DEFAULT_READ_CONTEXT_LINES - 1)
    end = min(end, line_count)
    if end < start:
        raise BusinessRuleError("Rule end_line must be greater than or equal to start_line.")

    truncated = False
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
        truncated = True
    return start, end, truncated


def _line_snippets(lines: list[str], start_line: int, *, limit: int = 5) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    if start_line == 0:
        return snippets
    for offset, line in enumerate(lines):
        text = line.strip()
        if not text:
            continue
        snippets.append(
            {
                "line": start_line + offset,
                "text": text[:500],
            }
        )
        if len(snippets) >= limit:
            break
    return snippets


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
