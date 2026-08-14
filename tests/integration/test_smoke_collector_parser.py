from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import smoke

TRACE_ID = "4b7820fe2757a2a5a83217f4160172ca"
RESOLVER_SERVER_ID = "6522ea5cda93dee6"
RESOLVER_CLIENT_ID = "f69cf87c6db4a637"
SHORTENER_SERVER_ID = "50611a8d9ad67e0c"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "collector_linux_split_exports.txt"
)


def linux_collector_logs() -> str:
    return FIXTURE_PATH.read_text()


def test_real_linux_split_exports_reconstruct_strict_trace_topology() -> None:
    spans = smoke._exported_spans(linux_collector_logs(), TRACE_ID)

    assert set(spans) == {
        ("resolver", RESOLVER_SERVER_ID, RESOLVER_CLIENT_ID, "Client"),
        ("resolver", "", RESOLVER_SERVER_ID, "Server"),
        ("shortener", RESOLVER_CLIENT_ID, SHORTENER_SERVER_ID, "Server"),
    }
    assert (
        smoke._strict_client_span_id(
            spans,
            RESOLVER_SERVER_ID,
            SHORTENER_SERVER_ID,
        )
        == RESOLVER_CLIENT_ID
    )


def test_trace_topology_rejects_broken_parent_relationship() -> None:
    spans = smoke._exported_spans(linux_collector_logs(), TRACE_ID)
    spans = [
        (service, "aaaaaaaaaaaaaaaa", span_id, kind)
        if span_id == SHORTENER_SERVER_ID
        else (service, parent_id, span_id, kind)
        for service, parent_id, span_id, kind in spans
    ]

    assert (
        smoke._strict_client_span_id(
            spans,
            RESOLVER_SERVER_ID,
            SHORTENER_SERVER_ID,
        )
        is None
    )


def test_compose_logs_combines_stdout_and_stderr(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="stdout evidence\n",
        stderr="stderr evidence\n",
    )
    monkeypatch.setattr(smoke.subprocess, "run", lambda *args, **kwargs: completed)

    assert smoke.compose_logs("otel-collector") == "stdout evidence\nstderr evidence"


def test_collector_evidence_accumulates_across_polling_reads(monkeypatch) -> None:
    raw_logs = linux_collector_logs()
    resolver_boundary = raw_logs.index("otel-collector-1  | 2026-08-14T02:47:11.048Z\tinfo\tTraces")
    polls = iter((raw_logs[:resolver_boundary], raw_logs[resolver_boundary:]))
    monkeypatch.setattr(smoke, "compose_logs", lambda _service: next(polls))
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)

    assert (
        smoke.wait_for_collector_evidence(
            TRACE_ID,
            RESOLVER_SERVER_ID,
            SHORTENER_SERVER_ID,
            timeout_seconds=1.0,
        )
        == RESOLVER_CLIENT_ID
    )
