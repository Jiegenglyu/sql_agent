from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any


@dataclass
class TokenUsageSnapshot:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0

    def add(self, usage: dict[str, Any]) -> None:
        prompt_tokens = _int_value(usage.get("prompt_tokens", usage.get("input_tokens")))
        completion_tokens = _int_value(usage.get("completion_tokens", usage.get("output_tokens")))
        total_tokens = _int_value(usage.get("total_tokens"))
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.requests += 1


_current_usage: ContextVar[TokenUsageSnapshot | None] = ContextVar("current_token_usage", default=None)
_total_usage = TokenUsageSnapshot()
_total_usage_lock = Lock()


def begin_token_usage() -> Token[TokenUsageSnapshot | None]:
    return _current_usage.set(TokenUsageSnapshot())


def finish_token_usage(token: Token[TokenUsageSnapshot | None]) -> dict[str, int]:
    snapshot = _current_usage.get() or TokenUsageSnapshot()
    _current_usage.reset(token)
    return token_usage_dict(snapshot)


def record_token_usage(usage: dict[str, Any] | None) -> None:
    if not usage:
        return

    current = _current_usage.get()
    if current is not None:
        current.add(usage)

    with _total_usage_lock:
        _total_usage.add(usage)


def get_total_token_usage() -> dict[str, int]:
    with _total_usage_lock:
        return token_usage_dict(_total_usage)


def empty_token_usage() -> dict[str, int]:
    return token_usage_dict(TokenUsageSnapshot())


def token_usage_dict(snapshot: TokenUsageSnapshot) -> dict[str, int]:
    return asdict(snapshot)


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
