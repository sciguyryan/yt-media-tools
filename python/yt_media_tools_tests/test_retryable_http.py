"""Retryable HTTP status observation contracts shared by the Python tools."""

from __future__ import annotations

import argparse

import pytest

from yt_media_tools.retryable_http import RetryableHttpObserver, http_client_status


def test_observer_records_only_configured_http_client_errors() -> None:
    observer = RetryableHttpObserver((403, 429))

    assert observer.observe_text("ERROR: HTTP Error 403: Forbidden") == (403,)
    assert observer.observe_text("request failed with status code 429") == (429,)
    assert observer.observe_text("HTTP Error 404: Not Found") == ()
    assert observer.observed == (403, 429)


def test_observer_does_not_treat_unlabelled_numbers_as_http_statuses() -> None:
    observer = RetryableHttpObserver((403,))

    assert observer.observe_text("video 403 has 429 views") == ()
    assert observer.observed == ()


def test_observer_prefers_structured_exception_statuses() -> None:
    class Response:
        status_code = 429

    error = RuntimeError("request rejected")
    error.response = Response()  # type: ignore[attr-defined]
    observer = RetryableHttpObserver((429,))

    assert observer.observe_exception(error) == (429,)


@pytest.mark.parametrize("value", ["399", "500", "forbidden"])
def test_http_client_status_rejects_values_outside_the_400_series(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        http_client_status(value)
