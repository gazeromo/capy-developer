from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_LIMIT = 64 * 1024
WINDOWS_CREATE_SUSPENDED = 0x00000004


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
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
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


def _resume_windows_process(process_id: int) -> None:
    """Resume the single primary thread of a newly suspended process."""
    import ctypes
    from ctypes import wintypes

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel.Thread32First.restype = wintypes.BOOL
    kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel.Thread32Next.restype = wintypes.BOOL
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or int(snapshot) == invalid:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == process_id:
                thread = kernel.OpenThread(0x0002, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
                finally:
                    kernel.CloseHandle(thread)
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        raise OSError("suspended Windows process has no primary thread")
    finally:
        kernel.CloseHandle(snapshot)


def _terminate_windows_job(job: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    if not kernel.TerminateJobObject(wintypes.HANDLE(job), 1):
        raise ctypes.WinError(ctypes.get_last_error())


def _close_windows_job(job: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    if not kernel.CloseHandle(wintypes.HANDLE(job)):
        raise ctypes.WinError(ctypes.get_last_error())


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


class _BoundedCapture:
    def __init__(self, limit: int = OUTPUT_LIMIT):
        self.limit = limit
        self.total = 0
        self.small = bytearray()
        self.head = bytearray()
        self.tail = bytearray()

    def add(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self.head:
            self.tail = (self.tail + chunk)[-(self.limit // 2):]
            return
        self.small.extend(chunk)
        if len(self.small) > self.limit:
            half = self.limit // 2
            self.head = self.small[:half]
            self.tail = self.small[-half:]
            self.small.clear()

    def result(self) -> tuple[str, int]:
        if not self.head:
            return bytes(self.small).decode("utf-8", "replace"), 0
        marker = f"\n... {self.total - self.limit} byte(s) omitted ...\n".encode()
        kept = max(0, self.limit - len(marker))
        head_size = kept // 2
        tail_size = kept - head_size
        payload = bytes(self.head[:head_size]) + marker + bytes(self.tail[-tail_size:])
        return payload.decode("utf-8", "replace"), self.total - self.limit


def _drain(stream, capture: _BoundedCapture) -> None:
    try:
        for chunk in iter(lambda: stream.read(8192), b""):
            capture.add(chunk)
    except (OSError, ValueError):
        pass


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
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | WINDOWS_CREATE_SUSPENDED
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
            _resume_windows_process(process.pid)
        except OSError:
            if windows_job is not None:
                _terminate_windows_job(windows_job)
                _close_windows_job(windows_job)
            else:
                process.kill()
            process.wait(timeout=5)
            raise
    stdout_capture = _BoundedCapture()
    stderr_capture = _BoundedCapture()
    readers = [
        threading.Thread(target=_drain, args=(process.stdout, stdout_capture), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr_capture), daemon=True),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        try:
            process.wait(timeout=timeout)
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
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        if windows_job is not None:
            _close_windows_job(windows_job)
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for reader in readers:
            reader.join(timeout=1)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        for reader in readers:
            reader.join(timeout=1)
    stdout_text, stdout_omitted = stdout_capture.result()
    stderr_text, stderr_omitted = stderr_capture.result()
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
