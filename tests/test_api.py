from datetime import datetime, timezone

import jwt

from shared.core import SessionLocal
from shared.models import Problem, Submission, Verdict, UserType, User

from .conftest import register, login, auth, set_user, create_problem


def create_tag(client, headers, slug="math", name="Math"):
    return client.post("/problems/tag", json={"name": name, "slug": slug}, headers=headers)


# ---------------------------------------------------------------- auth

def test_refresh_token_lives_for_refresh_expiry_days(client):
    register(client, "bob")
    tokens = login(client, "bob")

    claims = jwt.decode(tokens["refresh_token"], "test-secret-key-that-is-at-least-32-bytes", algorithms=["HS256"])
    lifetime = datetime.fromtimestamp(claims["exp"], timezone.utc) - datetime.now(timezone.utc)
    assert lifetime.days >= 6

    res = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 200
    assert res.json()["access_token"]


def test_access_token_is_rejected_as_refresh_token(client):
    register(client, "bob")
    tokens = login(client, "bob")
    res = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert res.status_code == 401


# ---------------------------------------------------------------- tags

def test_admin_can_create_tag(client, admin_headers):
    res = create_tag(client, admin_headers)
    assert res.status_code == 201
    assert res.json() == {"name": "Math", "slug": "math"}


def test_duplicate_tag_conflicts(client, admin_headers):
    assert create_tag(client, admin_headers).status_code == 201
    assert create_tag(client, admin_headers).status_code == 409


def test_non_admin_cannot_create_tag(client, user_headers):
    assert create_tag(client, user_headers).status_code == 403


def test_anonymous_cannot_create_tag(client):
    assert create_tag(client, {}).status_code == 401


def test_invalid_tag_slug_rejected(client, admin_headers):
    assert create_tag(client, admin_headers, slug="Not A Slug").status_code == 422
    assert create_tag(client, admin_headers, slug="x" * 51).status_code == 422
    assert create_tag(client, admin_headers, name="   ").status_code == 422


# ---------------------------------------------------------------- problems

def test_problem_creation_end_to_end_with_new_tag(client, admin_headers, s3):
    create_tag(client, admin_headers)
    body = create_problem(client, admin_headers)
    assert body["tags"] == ["math"]
    assert body["testcases"] == 1
    assert len(s3.keys("testcases")) == 2


def test_first_page_starts_at_first_problem(client, admin_headers):
    create_tag(client, admin_headers)
    for i in range(6):
        create_problem(client, admin_headers, problem_id=f"P{i}")

    page1 = client.get("/problems/?page=1&limit=5").json()
    page2 = client.get("/problems/?page=2&limit=5").json()
    assert [p["id"] for p in page1] == ["P0", "P1", "P2", "P3", "P4"]
    assert [p["id"] for p in page2] == ["P5"]


def test_update_problem(client, admin_headers):
    create_tag(client, admin_headers)
    create_tag(client, admin_headers, slug="dp", name="DP")
    create_problem(client, admin_headers, visibility=False)

    res = client.patch("/problems/P1", json={"title": "New", "tags": ["dp"], "visibility": True, "editorial": "hint"}, headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "New"
    assert body["tags"] == ["dp"]
    assert body["visibility"] is True
    assert body["editorial"] == "hint"

    # now visible to anonymous users
    assert client.get("/problems/P1").status_code == 200


def test_update_problem_validation(client, admin_headers, user_headers):
    create_tag(client, admin_headers)
    create_problem(client, admin_headers)

    assert client.patch("/problems/P1", json={"tags": ["nope"]}, headers=admin_headers).status_code == 400
    assert client.patch("/problems/P1", json={"title": None}, headers=admin_headers).status_code == 400
    assert client.patch("/problems/P1", json={"time_limit_sec": 0}, headers=admin_headers).status_code == 422
    assert client.patch("/problems/NOPE", json={"title": "x"}, headers=admin_headers).status_code == 404
    assert client.patch("/problems/P1", json={"title": "x"}, headers=user_headers).status_code == 403


def test_delete_problem_by_id(client, admin_headers, user_headers, s3):
    create_tag(client, admin_headers)
    create_problem(client, admin_headers)
    client.post("/submissions/", json={"problem_id": "P1", "code": "print(3)", "language": "PY"}, headers=user_headers)

    assert client.delete("/problems/P1", headers=user_headers).status_code == 403
    assert client.delete("/problems/P1", headers=admin_headers).status_code == 204
    assert client.get("/problems/P1", headers=admin_headers).status_code == 404
    assert s3.keys("testcases") == []
    assert s3.keys("submissions") == []
    assert client.delete("/problems/P1", headers=admin_headers).status_code == 404


def test_rejudge_resets_and_requeues(client, admin_headers, user_headers, enqueued):
    create_tag(client, admin_headers)
    create_problem(client, admin_headers)
    ids = [
        client.post("/submissions/", json={"problem_id": "P1", "code": "print(3)", "language": "PY"}, headers=user_headers).json()["id"]
        for _ in range(2)
    ]
    enqueued.clear()

    session = SessionLocal()
    for submission in session.query(Submission).all():
        submission.verdict = Verdict.ACCEPTED
        submission.walltime_ms = 12
    session.query(Problem).filter(Problem.id == "P1").update({Problem.accepted_submissions: 2})
    session.commit()
    session.close()

    assert client.post("/problems/P1/rejudge", headers=user_headers).status_code == 403
    res = client.post("/problems/P1/rejudge", headers=admin_headers)
    assert res.status_code == 202
    assert res.json() == {"problem_id": "P1", "requeued": 2}
    assert enqueued == ids

    session = SessionLocal()
    assert {s.verdict for s in session.query(Submission).all()} == {Verdict.PENDING}
    assert {s.walltime_ms for s in session.query(Submission).all()} == {None}
    assert session.get(Problem, "P1").accepted_submissions == 0
    session.close()


# ---------------------------------------------------------------- submissions

def test_submission_counts_and_enqueues(client, admin_headers, user_headers, enqueued):
    create_tag(client, admin_headers)
    create_problem(client, admin_headers)

    res = client.post("/submissions/", json={"problem_id": "P1", "code": "print(3)", "language": "PY"}, headers=user_headers)
    assert res.status_code == 201
    assert res.json()["code"] == "print(3)"
    assert enqueued == [res.json()["id"]]

    session = SessionLocal()
    assert session.get(Problem, "P1").total_submissions == 1
    session.close()


def test_submission_shows_failing_testcase(client, admin_headers, user_headers, s3):
    create_tag(client, admin_headers)
    create_problem(client, admin_headers)
    sub_id = client.post("/submissions/", json={"problem_id": "P1", "code": "print(4)", "language": "PY"}, headers=user_headers).json()["id"]

    session = SessionLocal()
    submission = session.get(Submission, sub_id)
    input_key = next(k for k in s3.keys("testcases") if k.endswith("1.txt"))
    submission.verdict = Verdict.WRONG_ANSWER
    submission.incorrect_testcase_key = input_key
    session.commit()
    session.close()

    body = client.get(f"/submissions/{sub_id}").json()
    assert body["verdict"] == "WA"
    assert body["incorrect_testcase"] in ("1 2\n", "3\n")
    assert body["code"] == "print(4)"


# ---------------------------------------------------------------- users

def test_view_other_users_profile(client, user_headers):
    register(client, "carol")
    set_user("carol", is_verified=True)

    res = client.get("/users/carol", headers=user_headers)
    assert res.status_code == 200, res.text
    assert res.json()["username"] == "carol"
    assert "email" not in res.json()

    register(client, "dave")  # unverified
    assert client.get("/users/dave").status_code == 404


def test_user_submissions_and_solved_problems(client, admin_headers, user_headers):
    create_tag(client, admin_headers)
    create_problem(client, admin_headers, problem_id="P1")
    create_problem(client, admin_headers, problem_id="P2")
    for pid in ("P1", "P1", "P2"):
        client.post("/submissions/", json={"problem_id": pid, "code": "x", "language": "PY"}, headers=user_headers)

    session = SessionLocal()
    for submission in session.query(Submission).filter(Submission.problem_id == "P1").all():
        submission.verdict = Verdict.ACCEPTED
    session.commit()
    session.close()

    subs = client.get("/users/alice/submissions").json()
    assert len(subs) == 3
    assert all(s["username"] == "alice" for s in subs)

    solved = client.get("/users/alice/solved_problems").json()
    assert solved == [{"id": "P1", "title": "Problem P1"}]

    # hidden problems don't leak through either list
    client.patch("/problems/P1", json={"visibility": False}, headers=admin_headers)
    assert client.get("/users/alice/solved_problems").json() == []
    assert len(client.get("/users/alice/submissions").json()) == 1

    assert client.get("/users/nobody/submissions").status_code == 404


def test_admin_can_promote_and_demote(client, admin_headers, user_headers):
    res = client.patch("/users/alice/role", json={"user_type": "ADMIN"}, headers=admin_headers)
    assert res.status_code == 200
    assert res.json() == {"username": "alice", "user_type": "ADMIN"}

    # alice can now create tags
    assert create_tag(client, user_headers).status_code == 201

    res = client.patch("/users/alice/role", json={"user_type": "USER"}, headers=admin_headers)
    assert res.json()["user_type"] == "USER"
    assert create_tag(client, user_headers, slug="dp").status_code == 403


def test_role_change_guards(client, admin_headers, user_headers):
    assert client.patch("/users/admin/role", json={"user_type": "ADMIN"}, headers=user_headers).status_code == 403
    assert client.patch("/users/admin/role", json={"user_type": "USER"}, headers=admin_headers).status_code == 400
    assert client.patch("/users/ghost/role", json={"user_type": "ADMIN"}, headers=admin_headers).status_code == 404
    assert client.patch("/users/alice/role", json={"user_type": "ROOT"}, headers=admin_headers).status_code == 422
