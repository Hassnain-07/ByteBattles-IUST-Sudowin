import io
import json
import os
import tempfile
import zipfile

# config.py reads the environment at import time, so this has to run before any project import
_tmp_dir = tempfile.mkdtemp(prefix="bytebattles-tests-")
os.environ.update({
    "DB_URL": f"sqlite:///{_tmp_dir}/test.db",
    "REDIS_HOST": "localhost", "REDIS_PORT": "6379", "REDIS_DB": "0",
    "S3_ENDPOINT_URL": "http://localhost:9000", "S3_ACCESS_KEY": "x", "S3_SECRET_KEY": "x",
    "S3_REGION": "us-east-1", "S3_SIGNATURE_VERSION": "s3v4",
    "SECRET_KEY": "test-secret-key-that-is-at-least-32-bytes", "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30", "REFRESH_TOKEN_EXPIRE_DAYS": "7", "DUMMY_PASS": "dummy_password",
    "TESTCASE_BUCKET": "testcases", "SUBMISSION_BUCKET": "submissions",
    "CONTAINER_POOL_THRESHOLD": "1", "CONTAINER_WORKER_COUNT": "1", "MAX_MEMCAP_GB": "1", "MAX_PIDS": "64",
    "ACQUIRE_TIMEOUT_SECONDS": "1", "WORKSPACE_DIR": "/workspace",
    "MINIMUM_JUDGE_WORKER": "1", "MAXIMUM_JUDGE_WORKER": "2", "JUDGE_WORKER_TIMEOUT": "120",
    "MAX_JUDGE_ATTEMPTS": "3",
    "REDIS_JOB_LIST": "judge:queue", "REDIS_RESULT_CHANNEL": "submission_updates",
    "SHUTDOWN_KEY": "control:shutdown", "WORKER_PREFIX": "worker", "WARM_QUEUE_PREFIX": "warm",
})

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from shared.core import storage as storage_module
from shared.core import Base, engine, SessionLocal
from shared.models import User, UserType


class FakeS3:
    """In-memory stand-in for the boto3 S3 client methods the storage layer uses."""

    def __init__(self):
        self.objects = {}

    def _missing(self, op):
        return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, op)

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._missing("GetObject")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._missing("HeadObject")
        return {}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop((Bucket, obj["Key"]), None)

    def get_paginator(self, name):
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for b, k in fake.objects if b == Bucket and k.startswith(Prefix))
                for i in range(0, max(len(keys), 1), 1000):
                    chunk = keys[i:i + 1000]
                    yield {"Contents": [{"Key": k} for k in chunk]} if chunk else {}

        return Paginator()

    def keys(self, bucket):
        return sorted(k for b, k in self.objects if b == bucket)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(storage_module, "get_s3_client", lambda: fake)
    storage_module.get_storage_testcases.cache_clear()
    storage_module.get_storage_submission_code.cache_clear()
    yield fake
    storage_module.get_storage_testcases.cache_clear()
    storage_module.get_storage_submission_code.cache_clear()


@pytest.fixture
def db_reset():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db(db_reset):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def enqueued(monkeypatch):
    jobs = []
    from api.app.routes import problems, submissions
    monkeypatch.setattr(submissions, "enqueue_job", jobs.append)
    monkeypatch.setattr(problems, "enqueue_job", jobs.append)
    return jobs


@pytest.fixture
def client(db_reset, s3, enqueued):
    from api.app.main import app
    return TestClient(app)


def register(client, username, password="password123"):
    res = client.post("/auth/register", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": password,
        "conf_password": password,
    })
    assert res.status_code == 201, res.text
    return res.json()


def login(client, username, password="password123"):
    res = client.post("/auth/login", data={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def set_user(username, **fields):
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.username == username).one()
        for key, value in fields.items():
            setattr(user, key, value)
        session.commit()
    finally:
        session.close()


@pytest.fixture
def admin_headers(client):
    register(client, "admin")
    set_user("admin", user_type=UserType.ADMIN, is_verified=True)
    return auth(login(client, "admin")["access_token"])


@pytest.fixture
def user_headers(client):
    register(client, "alice")
    set_user("alice", is_verified=True)
    return auth(login(client, "alice")["access_token"])


def make_tests_zip(name="tests", cases=(("1.txt", b"1 2\n", b"3\n"),)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for filename, inp, out in cases:
            zf.writestr(f"{name}/inputs/{filename}", inp)
            zf.writestr(f"{name}/outputs/{filename}", out)
    return buf.getvalue()


def create_problem(client, headers, problem_id="P1", tags=("math",), visibility=True, **overrides):
    form = {
        "id": problem_id,
        "title": f"Problem {problem_id}",
        "description": "Add two numbers",
        "difficulty": "EASY",
        "constraints": '["1 <= a, b <= 10"]',
        "tags": json.dumps(list(tags)),
        "sample_io": '{"1 2": "3"}',
        "input_desc": "two ints",
        "output_desc": "their sum",
        "memory_limit_mb": "256",
        "time_limit_sec": "1",
        "visibility": str(visibility).lower(),
    }
    form.update(overrides)
    res = client.post(
        "/problems/",
        data=form,
        files={"tests_zip": ("tests.zip", make_tests_zip(), "application/zip")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()
