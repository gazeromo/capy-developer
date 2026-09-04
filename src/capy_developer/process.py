from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_LIMIT = 64 * 1024


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated_bytes: int
    stderr_truncated_bytes: int
    duration_ms: int
    timed_out: bool
    started_at: str | None = None
    terminal_at: str | None = None


def _bounded(payload: bytes, limit: int = OUTPUT_LIMIT) -> tuple[str, int]:
    if len(payload) <= limit:
        return payload.decode("utf-8", "replace"), 0
    half = limit // 2
    omitted = len(payload) - limit
    marker = f"\n... {omitted} byte(s) omitted ...\n".encode()
    kept = max(0, limit - len(marker))
    head = kept // 2
    tail = kept - head
    value = payload[:head] + marker + payload[-tail:]
    return value.decode("utf-8", "replace"), omitted


def run_process(
    arguments: list[str], *, cwd: Path, environment: dict[str, str], timeout: float,
) -> ProcessResult:
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started = time.monotonic()
    options: dict = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(
        arguments,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        **options,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            stdout, stderr = process.communicate()
    stdout_text, stdout_omitted = _bounded(stdout)
    stderr_text, stderr_omitted = _bounded(stderr)
    terminal_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return ProcessResult(
        None if timed_out else process.returncode,
        stdout_text,
        stderr_text,
        stdout_omitted,
        stderr_omitted,
        round((time.monotonic() - started) * 1000),
        timed_out,
        started_at,
        terminal_at,
    )


def combine_process_results(*results: ProcessResult) -> ProcessResult:
    """Combine subprocess receipts while retaining the per-stream storage cap."""
    stdout, extra_stdout = _bounded("".join(item.stdout for item in results).encode())
    stderr, extra_stderr = _bounded("".join(item.stderr for item in results).encode())
    return ProcessResult(
        results[-1].exit_code,
        stdout,
        stderr,
        sum(item.stdout_truncated_bytes for item in results) + extra_stdout,
        sum(item.stderr_truncated_bytes for item in results) + extra_stderr,
        sum(item.duration_ms for item in results),
        results[-1].timed_out,
        results[0].started_at,
        results[-1].terminal_at,
    )
