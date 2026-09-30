import logging

import pytest

from shared.core import SessionLocal
from shared.models import Problem, Submission, User, Verdict, Language, Difficulty

from judge.judge_worker import worker as worker_module
from judge.judge_worker.database import Database
from judge.judge_worker.executor import parse_time_stats, normalize_output
from judge.judge_worker.pipeline import JudgePipeline
from judge.judge_worker.types import SubmissionResult


# ---------------------------------------------------------------- executor helpers

def test_parse_time_stats_converts_seconds_to_ms():
    assert parse_time_stats("0.25 3120\n", time_limit_sec=2, memory_limit_kb=262144) == (250, 3120)


def test_parse_time_stats_skips_gnu_time_status_lines():
    stderr = "Command exited with non-zero status 137\n2.00 5000\n"
    assert parse_time_stats(stderr, time_limit_sec=1, memory_limit_kb=4000) == (1000, 4000)


def test_parse_time_stats_raises_on_garbage():
    with pytest.raises(RuntimeError):
        parse_time_stats("", time_limit_sec=1, memory_limit_kb=1)


def test_normalize_output_ignores_whitespace_layout():
    assert normalize_output("1 2\n3  \n\n") == normalize_output("1\n2\n3")
    assert normalize_output("1 2") != normalize_output("12")


# ---------------------------------------------------------------- pipeline

def make_pipeline():
    pipeline = object.__new__(JudgePipeline)  # skip docker.from_env()
    pipeline.db = Database()
    return pipeline


def seed_submission(verdict=Verdict.PENDING, accepted=0):
    session = SessionLocal()
    session.add(User(id=1, username="u", email="u@example.com", password_hash="x"))
    session.add(Problem(
        id="P1", title="t", difficulty=Difficulty.EASY, description="d", constraints=[], input_desc="i",
        output_desc="o", sample_io={}, memory_limit_mb=64, time_limit_sec=1, accepted_submissions=accepted,
    ))
    session.add(Submission(id=1, language=Language.PYTHON, code_object_key="k", problem_id="P1", user_id=1, verdict=verdict))
    session.commit()
    session.close()


def accepted_count():
    session = SessionLocal()
    try:
        return session.get(Problem, "P1").accepted_submissions
    finally:
        session.close()


def test_accepted_count_follows_verdict_transitions(db):
    seed_submission()
    pipeline = make_pipeline()

    pipeline._update_submission_result(1, SubmissionResult(submission_id=1, verdict=Verdict.ACCEPTED, runtime_ms=5))
    assert accepted_count() == 1

    # judging the same submission AC again (e.g. duplicate queue entry) doesn't double count
    pipeline._update_submission_result(1, SubmissionResult(submission_id=1, verdict=Verdict.ACCEPTED))
    assert accepted_count() == 1

    pipeline._update_submission_result(1, SubmissionResult(submission_id=1, verdict=Verdict.WRONG_ANSWER))
    assert accepted_count() == 0


def test_problem_without_testcases_is_rejected(db):
    seed_submission()
    session = SessionLocal()
    with pytest.raises(ValueError):
        make_pipeline()._get_testcases(session, "P1")
    session.close()


# ---------------------------------------------------------------- worker retries

class FakeRedis:
    def __init__(self, jobs):
        self.lists = {"judge:queue": list(jobs)}
        self.values = {}
        self.hashes = {}

    def get(self, key):
        if key == "control:shutdown":
            return "1" if not self.lists["judge:queue"] else "0"
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = str(value)

    def delete(self, key):
        self.values.pop(key, None)

    def lpush(self, key, value):
        self.lists[key].insert(0, str(value))

    def brpop(self, key, timeout=0):
        return (key, self.lists[key].pop()) if self.lists[key] else None

    def hincrby(self, key, field, amount):
        h = self.hashes.setdefault(key, {})
        h[str(field)] = h.get(str(field), 0) + amount
        return h[str(field)]

    def hdel(self, key, field):
        self.hashes.get(key, {}).pop(str(field), None)


class FakePipeline:
    def __init__(self, error):
        self.error = error
        self.calls = 0
        self.results = []

    def process_submission(self, submission_id):
        self.calls += 1
        raise self.error

    def _update_submission_result(self, submission_id, result):
        self.results.append(result)


def make_worker(redis, pipeline):
    worker = object.__new__(worker_module.JudgeWorker)  # skip docker/redis connections
    worker.identifier = 1
    worker.local_shutdown_key = "worker:1:shutdown"
    worker.local_heartbeat_key = "worker:1:heartbeat"
    worker.current_submission_key = "worker:1:submission"
    worker.redis = redis
    worker.pipeline = pipeline
    worker.log = logging.getLogger("test-worker")
    return worker


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(worker_module.time, "sleep", lambda s: None)


def test_worker_gives_up_after_max_attempts():
    redis = FakeRedis(["7"])
    pipeline = FakePipeline(RuntimeError("docker exploded"))
    make_worker(redis, pipeline)._consume_from_list()

    assert pipeline.calls == 3
    assert [r.verdict for r in pipeline.results] == [Verdict.SKIPPED]
    assert redis.hashes.get(worker_module.ATTEMPTS_KEY, {}) == {}
    assert "worker:1:submission" not in redis.values


def test_worker_does_not_retry_bad_data():
    redis = FakeRedis(["7"])
    pipeline = FakePipeline(ValueError("Submission 7 not found"))
    make_worker(redis, pipeline)._consume_from_list()

    assert pipeline.calls == 1
    assert [r.verdict for r in pipeline.results] == [Verdict.SKIPPED]


def test_worker_requeues_on_empty_pool_without_counting_attempts():
    redis = FakeRedis(["7"])

    class FlakyPipeline(FakePipeline):
        def process_submission(self, submission_id):
            self.calls += 1
            if self.calls <= 5:
                raise TimeoutError("No warm sandbox available for PY")
            return SubmissionResult(submission_id=submission_id, verdict=Verdict.ACCEPTED)

    pipeline = FlakyPipeline(None)
    make_worker(redis, pipeline)._consume_from_list()

    assert pipeline.calls == 6
    assert pipeline.results == []
