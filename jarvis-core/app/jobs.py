"""
In-memory background jobs for slow LLM work (``POST /chat`` → ``GET /jobs/{id}``).

Why this shape:
- CPU inference with tool use can take several minutes, longer than any sane HTTP timeout,
  so the request returns a job id at once and the client polls.
- Ollama serves one request at a time (``OLLAMA_NUM_PARALLEL=1``), so only ``max_running``
  jobs (default 1) may run; further submissions are refused immediately (``JobsBusyError``)
  instead of queueing behind a multi-minute run.
- Jobs live in process memory: they are lost when core restarts (clients then get 404) and
  are bounded in count and age so a long-running process can't grow without limit.
- A Python thread can't be killed. A job that exceeds ``timeout_s`` is reported as an error
  and stops counting as running; if its thread finishes later, the result is discarded.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum

logger = logging.getLogger("jarvis.jobs")


class JobStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class Job:
    id: str
    status: JobStatus
    created_at: float  # monotonic seconds
    finished_at: float | None = None
    reply: str | None = None
    error: str | None = None


class JobsBusyError(RuntimeError):
    """The maximum number of jobs is already running."""


def _default_spawn(target: Callable[[], None]) -> None:
    # Daemon: an in-flight LLM call must not block container shutdown.
    threading.Thread(target=target, name="jarvis-job", daemon=True).start()


class JobStore:
    """Thread-safe registry of background jobs. ``spawn`` and ``clock`` are injectable for tests."""

    def __init__(
        self,
        *,
        max_running: int = 1,
        max_jobs: int = 200,
        ttl_s: float = 3600.0,
        timeout_s: float = 900.0,
        describe_error: Callable[[Exception], str] | None = None,
        spawn: Callable[[Callable[[], None]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_running = max_running
        self._max_jobs = max_jobs
        self._ttl_s = ttl_s
        self._timeout_s = timeout_s
        self._describe_error = describe_error or (lambda exc: "The job failed.")
        self._spawn = spawn or _default_spawn
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------------------
    def submit(self, work: Callable[[], str]) -> Job:
        """Start ``work`` in the background and return the new (running) job.

        Raises ``JobsBusyError`` if ``max_running`` jobs are already running.
        """
        with self._lock:
            self._expire_locked()
            running = sum(1 for j in self._jobs.values() if j.status is JobStatus.RUNNING)
            if running >= self._max_running:
                raise JobsBusyError("A job is already running")
            self._evict_locked()
            job = Job(id=uuid.uuid4().hex, status=JobStatus.RUNNING, created_at=self._clock())
            self._jobs[job.id] = job

        try:
            self._spawn(lambda: self._run(job.id, work))
        except Exception as exc:  # e.g. can't start a thread: don't leave a phantom "running" job
            self._finish(job.id, error=self._describe_error(exc))
            logger.error("Could not start job %s: %s", job.id, exc.__class__.__name__)
        return self.get(job.id) or job

    def get(self, job_id: str) -> Job | None:
        """Return a snapshot of the job, or None if unknown or expired."""
        with self._lock:
            self._expire_locked()
            return self._jobs.get(job_id)

    # -- internals ------------------------------------------------------------------------
    def _run(self, job_id: str, work: Callable[[], str]) -> None:
        try:
            reply = work()
        except Exception as exc:  # noqa: BLE001 - every failure is reported via the job
            logger.warning("Job %s failed: %s", job_id, exc.__class__.__name__)
            self._finish(job_id, error=self._describe_error(exc))
            return
        self._finish(job_id, reply=reply)

    def _finish(self, job_id: str, *, reply: str | None = None, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status is not JobStatus.RUNNING:
                # Timed out (or evicted) meanwhile: the client was already told; drop the result.
                logger.info("Discarding late result for job %s", job_id)
                return
            now = self._clock()
            self._jobs[job_id] = replace(
                job,
                status=JobStatus.ERROR if error is not None else JobStatus.DONE,
                finished_at=now,
                reply=reply if error is None else None,
                error=error,
            )
            logger.info("Job %s %s after %.1fs", job_id,
                        "failed" if error is not None else "done", now - job.created_at)

    def _expire_locked(self) -> None:
        """Time out overdue running jobs and forget finished jobs older than the TTL."""
        now = self._clock()
        for job_id, job in list(self._jobs.items()):
            if job.status is JobStatus.RUNNING and now - job.created_at > self._timeout_s:
                logger.warning("Job %s timed out after %.0fs", job_id, now - job.created_at)
                self._jobs[job_id] = replace(
                    job, status=JobStatus.ERROR, finished_at=now,
                    error="Jarvis took too long to answer. Please try again.",
                )
            elif job.finished_at is not None and now - job.finished_at > self._ttl_s:
                del self._jobs[job_id]

    def _evict_locked(self) -> None:
        """Make room for one more job by dropping the oldest finished ones."""
        finished = sorted(
            (j for j in self._jobs.values() if j.status is not JobStatus.RUNNING),
            key=lambda j: j.finished_at or j.created_at,
        )
        while len(self._jobs) >= self._max_jobs and finished:
            del self._jobs[finished.pop(0).id]
