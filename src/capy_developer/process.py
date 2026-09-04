from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_LIMIT = 64 * 1024


def _assign_windows_kill_job(process: subprocess.Popen) -> int:
    """Own a Windows process tree with kill-on-close semantics."""
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = EXTENDED_LIMITS()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    return int(job)


def _terminate_windows_job(job: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    if not kernel.TerminateJobObject(wintypes.HANDLE(job), 1):
        raise ctypes.WinError(ctypes.get_last_error())


def _close_windows_job(job: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle(wintypes.HANDLE(job))


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
    windows_job = None
    if os.name == "nt":
        try:
            windows_job = _assign_windows_kill_job(process)
        except OSError:
            process.kill()
            process.communicate(timeout=5)
            raise
    timed_out = False
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                _terminate_windows_job(windows_job)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    stdout, stderr = process.communicate(timeout=1)
                except subprocess.TimeoutExpired as error:
                    stdout = error.output or b""
                    stderr = error.stderr or b""
                    if process.stdout is not None:
                        process.stdout.close()
                    if process.stderr is not None:
                        process.stderr.close()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
    finally:
        if windows_job is not None:
            _close_windows_job(windows_job)
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
