"""Tests for app.jobs.JobStore (in-memory background jobs)."""

from __future__ import annotations

import threading

import pytest

from app.jobs import JobsBusyError, JobStatus, JobStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _deferred_store(clock: FakeClock, **kwargs) -> tuple[JobStore, list]:
    pending: list = []
    return JobStore(spawn=pending.append, clock=clock, **kwargs), pending


def test_real_thread_runs_job_to_completion():
    release = threading.Event()
    store = JobStore()

    def work() -> str:
        assert release.wait(5)
        return "answer"

    job = store.submit(work)
    assert job.status is JobStatus.RUNNING
    release.set()
    for _ in range(500):
        if store.get(job.id).status is not JobStatus.RUNNING:
            break
        threading.Event().wait(0.01)
    done = store.get(job.id)
    assert done.status is JobStatus.DONE and done.reply == "answer" and done.error is None


def test_only_one_job_runs_at_a_time(clock):
    store, pending = _deferred_store(clock)
    store.submit(lambda: "one")
    with pytest.raises(JobsBusyError):
        store.submit(lambda: "two")
    pending.pop()()
    assert store.submit(lambda: "three").status is JobStatus.RUNNING


def test_failure_is_described_without_exception_text(clock):
    store = JobStore(spawn=lambda t: t(), clock=clock, describe_error=lambda exc: "nope")

    def boom() -> str:
        raise RuntimeError("secret http://ollama:11434 detail")

    job = store.get(store.submit(boom).id)
    assert job.status is JobStatus.ERROR and job.error == "nope" and job.reply is None


def test_overdue_job_times_out_and_frees_the_slot(clock):
    store, pending = _deferred_store(clock, timeout_s=900)
    job = store.submit(lambda: "late")
    clock.now += 901
    timed_out = store.get(job.id)
    assert timed_out.status is JobStatus.ERROR and "too long" in timed_out.error
    assert store.submit(lambda: "next").status is JobStatus.RUNNING  # slot freed


def test_late_result_after_timeout_is_discarded(clock):
    store, pending = _deferred_store(clock, timeout_s=900)
    job = store.submit(lambda: "late answer")
    clock.now += 901
    assert store.get(job.id).status is JobStatus.ERROR
    pending.pop(0)()  # the abandoned thread finally finishes
    assert store.get(job.id).status is JobStatus.ERROR
    assert store.get(job.id).reply is None


def test_finished_jobs_expire_after_ttl(clock):
    store = JobStore(spawn=lambda t: t(), clock=clock, ttl_s=3600)
    job = store.submit(lambda: "x")
    clock.now += 3599
    assert store.get(job.id) is not None
    clock.now += 2
    assert store.get(job.id) is None


def test_store_size_is_bounded(clock):
    store = JobStore(spawn=lambda t: t(), clock=clock, max_jobs=3)
    ids = []
    for _ in range(5):
        clock.now += 1
        ids.append(store.submit(lambda: "x").id)
    assert [store.get(i) is not None for i in ids] == [False, False, True, True, True]


def test_spawn_failure_leaves_no_running_job(clock):
    def broken_spawn(target) -> None:
        raise RuntimeError("can't start new thread")

    store = JobStore(spawn=broken_spawn, clock=clock, describe_error=lambda exc: "failed")
    job = store.submit(lambda: "x")
    assert job.status is JobStatus.ERROR and job.error == "failed"
    assert store.submit(lambda: "y").status is JobStatus.ERROR  # not blocked as "busy"


def test_job_ids_are_unique_uuid_hex(clock):
    store = JobStore(spawn=lambda t: t(), clock=clock)
    ids = {store.submit(lambda: "x").id for _ in range(50)}
    assert len(ids) == 50 and all(len(i) == 32 and int(i, 16) >= 0 for i in ids)
