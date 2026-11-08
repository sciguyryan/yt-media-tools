"""Shared observation of configured retryable HTTP client errors."""

from __future__ import annotations

import argparse
import re
import threading
from collections.abc import Iterable


TEMPORARY_FAILURE_EXIT_STATUS = 75

_HTTP_STATUS_PATTERNS = (
    re.compile(r"\bHTTP(?:\s+Error)?[\s:=]+(?P<status>4\d\d)\b", re.IGNORECASE),
    re.compile(r"\bstatus(?:\s+code)?[\s:=]+(?P<status>4\d\d)\b", re.IGNORECASE),
)


def http_client_status(value: str) -> int:
    """Parse one configured HTTP client-error status for argparse."""
    try:
        status = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("HTTP status must be an integer from 400 to 499") from exc
    if not 400 <= status <= 499:
        raise argparse.ArgumentTypeError("HTTP status must be between 400 and 499")
    return status


class RetryableHttpObserver:
    """Record configured HTTP statuses found at external integration boundaries."""

    def __init__(self, statuses: Iterable[int] = ()) -> None:
        self._configured = frozenset(statuses)
        self._observed: set[int] = set()
        self._lock = threading.Lock()

    @property
    def configured(self) -> frozenset[int]:
        """Return the configured retryable statuses."""
        return self._configured

    @property
    def observed(self) -> tuple[int, ...]:
        """Return matching observed statuses in deterministic order."""
        with self._lock:
            return tuple(sorted(self._observed))

    def observe_status(self, status: object) -> bool:
        """Record one structured status when it is configured as retryable."""
        try:
            parsed = int(status)
        except (TypeError, ValueError):
            return False
        if parsed not in self._configured:
            return False
        with self._lock:
            self._observed.add(parsed)
        return True

    def observe_text(self, text: str) -> tuple[int, ...]:
        """Record configured statuses named in external diagnostic text."""
        matches: set[int] = set()
        for pattern in _HTTP_STATUS_PATTERNS:
            for match in pattern.finditer(text):
                status = int(match.group("status"))
                if self.observe_status(status):
                    matches.add(status)
        return tuple(sorted(matches))

    def observe_exception(self, error: BaseException) -> tuple[int, ...]:
        """Observe structured response fields and the rendered exception text."""
        candidates = [
            getattr(error, "status", None),
            getattr(error, "status_code", None),
            getattr(error, "code", None),
        ]
        response = getattr(error, "response", None)
        if response is not None:
            candidates.extend((getattr(response, "status", None), getattr(response, "status_code", None)))
        for candidate in candidates:
            self.observe_status(candidate)
        self.observe_text(str(error))
        return self.observed


_observer = RetryableHttpObserver()


def configure_retryable_http_statuses(statuses: Iterable[int]) -> RetryableHttpObserver:
    """Install and return the observer for one CLI invocation."""
    global _observer
    _observer = RetryableHttpObserver(statuses)
    return _observer


def current_retryable_http_observer() -> RetryableHttpObserver:
    """Return the observer configured for the current CLI invocation."""
    return _observer
