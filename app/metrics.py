"""Atomic Prometheus textfile metrics for Netflix Watcher."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_METRICS_FILE = Path("/metrics/netflix-watcher.prom")
PRODUCT = "netflix-watcher"
COMMON_METRICS = {
    "service_up",
    "last_loop_success_timestamp_seconds",
    "last_dependency_success_timestamp_seconds",
    "consecutive_failures",
    "operations_success_total",
    "operations_failure_total",
    "last_operation_duration_seconds",
}
COUNTERS = {
    "operations_success_total",
    "operations_failure_total",
    "netflix_imap_poll_success_total",
    "netflix_imap_poll_failure_total",
    "netflix_matching_emails_total",
    "netflix_selenium_start_success_total",
    "netflix_selenium_start_failure_total",
    "netflix_workflow_success_total",
    "netflix_workflow_failure_total",
}


class Metrics:
    """Keep low-cardinality state and atomically publish each update."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.getenv("METRICS_FILE", str(DEFAULT_METRICS_FILE)))
        self._lock = threading.Lock()
        self._last_poll_publish = 0.0
        self._values: dict[str, float] = {
            "service_up": 0,
            "netflix_watcher_process_start_timestamp_seconds": time.time(),
            "last_loop_success_timestamp_seconds": 0,
            "last_dependency_success_timestamp_seconds": 0,
            "consecutive_failures": 0,
            "operations_success_total": 0,
            "operations_failure_total": 0,
            "last_operation_duration_seconds": 0,
            "netflix_imap_poll_success": 0,
            "netflix_imap_poll_success_total": 0,
            "netflix_imap_poll_failure_total": 0,
            "netflix_imap_last_success_timestamp_seconds": 0,
            "netflix_matching_emails_pending": 0,
            "netflix_matching_emails_total": 0,
            "netflix_selenium_available": -1,
            "netflix_selenium_start_success_total": 0,
            "netflix_selenium_start_failure_total": 0,
            "netflix_selenium_last_start_timestamp_seconds": 0,
            "netflix_workflow_stage": 0,
            "netflix_workflow_success_total": 0,
            "netflix_workflow_failure_total": 0,
            "netflix_workflow_last_success": -1,
            "netflix_workflow_last_timestamp_seconds": 0,
            "netflix_workflow_last_duration_seconds": 0,
        }

    def publish(self) -> None:
        with self._lock:
            self._write_locked()

    def set(self, name: str, value: float) -> None:
        self.update(**{name: value})

    def increment(self, name: str, amount: float = 1) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + amount
            self._write_locked()

    def update(self, **values: float) -> None:
        with self._lock:
            self._values.update({name: float(value) for name, value in values.items()})
            self._write_locked()

    def poll_success(self, pending: int, duration: float) -> None:
        now = time.time()
        now_monotonic = time.monotonic()
        with self._lock:
            self._values.update(
                {
                    "last_loop_success_timestamp_seconds": now,
                    "last_dependency_success_timestamp_seconds": now,
                    "consecutive_failures": 0,
                    "operations_success_total": self._values["operations_success_total"] + 1,
                    "last_operation_duration_seconds": duration,
                    "netflix_imap_poll_success": 1,
                    "netflix_imap_poll_success_total": self._values["netflix_imap_poll_success_total"] + 1,
                    "netflix_imap_last_success_timestamp_seconds": now,
                    "netflix_matching_emails_pending": pending,
                    "netflix_workflow_stage": 0 if pending == 0 else self._values["netflix_workflow_stage"],
                }
            )
            if pending == 0 and now_monotonic - self._last_poll_publish < 30:
                return
            self._last_poll_publish = now_monotonic
            self._write_locked()

    def poll_failure(self, duration: float) -> None:
        with self._lock:
            self._values.update(
                {
                    "consecutive_failures": self._values["consecutive_failures"] + 1,
                    "operations_failure_total": self._values["operations_failure_total"] + 1,
                    "last_operation_duration_seconds": duration,
                    "netflix_imap_poll_success": 0,
                    "netflix_imap_poll_failure_total": self._values["netflix_imap_poll_failure_total"] + 1,
                }
            )
            self._write_locked()

    def workflow_finished(self, success: bool, duration: float) -> None:
        counter = "netflix_workflow_success_total" if success else "netflix_workflow_failure_total"
        with self._lock:
            self._values[counter] += 1
            self._values.update(
                {
                    "netflix_workflow_stage": 5 if success else 6,
                    "netflix_workflow_last_success": int(success),
                    "netflix_workflow_last_timestamp_seconds": time.time(),
                    "netflix_workflow_last_duration_seconds": duration,
                }
            )
            self._write_locked()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for name, value in sorted(self._values.items()):
            sample = f'{name}{{product="{PRODUCT}"}}' if name in COMMON_METRICS else name
            lines.append(f"# TYPE {name} {'counter' if name in COUNTERS else 'gauge'}\n{sample} {value:g}")
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
