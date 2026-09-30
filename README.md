# ByteBattles

ByteBattles is a competitive programming platform: an online judge in the style of LeetCode or Codeforces. It is built around a **FastAPI** backend and a **Redis-driven asynchronous judge** that auto-scales. Admins publish problems with hidden testcases, users submit solutions in **C, C++ or Python**, and the judge compiles and runs every submission inside **pre-warmed, isolated Docker sandboxes** and returns a verdict.

The system is designed to be practical, fast, and scalable on a single machine while remaining ready for horizontal expansion later.

It ships with a lightweight **web frontend** (plain HTML/CSS/JS) at `http://localhost:3000`, so every feature can be used from the browser. The interactive API docs are at `http://localhost:8000/docs`.

The judge architecture diagram is in [`docs/Judge_Architecture.pdf`](docs/Judge_Architecture.pdf).

---

## Table of contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [API overview](#api-overview)
- [Verdicts](#verdicts)
- [How the judge works](#how-the-judge-works)
- [What was changed in this version](#what-was-changed-in-this-version)
- [Testing](#testing)
- [Configuration](#configuration)
- [Repository layout](#repository-layout)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [Known limitations and future improvements](#known-limitations-and-future-improvements)
- [License](#license)

---

## Highlights

- FastAPI backend for authentication, users, problems, tags and submissions
- JWT authentication (OAuth2 password flow) with access and refresh tokens, and Argon2 password hashing
- Role-based access: admins manage problems, tags and user roles
- Redis-backed asynchronous judging pipeline
- Multi-process and multi-threaded judge orchestration
- Spawns and destroys judge workers automatically depending on load (4–20 workers)
- Heartbeat checks for judge workers, with automatic retry of stuck or failed submissions (bounded, with a `SKP` verdict after repeated failures)
- Pre-warmed Docker sandbox pools for low-latency execution
- Isolated execution for C, C++ and Python, with CPU-time and memory measurement
- Verdicts: AC, WA, TLE, MLE, CE, RE
- PostgreSQL for persistent metadata, MinIO (S3-compatible) for testcases and submitted code
- Problem management: create, edit, show/hide, delete, and rejudge all submissions
- User profiles with submission history and solved problems
- Browser frontend served by nginx, with an automated test suite (pytest)

---

## Architecture

ByteBattles follows a queue-centric architecture:

```text
Browser (frontend :3000)          Swagger UI (:8000/docs)
        │  /api/*  (nginx reverse proxy)      │
        └──────────────┬──────────────────────┘
                       ▼
                 FastAPI API
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼               ▼
   PostgreSQL        MinIO        Redis job queue
  (metadata,     (testcases,           │
   verdicts)     source code)          ▼
                              Judge orchestrator
                                       │
                         ┌─────────────┴─────────────┐
                         ▼                           ▼
                   Judge workers              Sandbox manager
                  (4–20 processes)          (creator threads)
                         │                           │
                         └──── warm container pool ──┘
                                       │
                                       ▼
                         Docker isolated execution
                                       │
                                       ▼
                          Verdict written to PostgreSQL
```

### Core services

| Service | Role | Port |
|---|---|---|
| `frontend` | nginx serving the web UI and proxying `/api/*` to the API | 3000 |
| `api` | FastAPI: auth, users, problems, tags, submissions | 8000 |
| `judge` | Orchestrator, judge workers and sandbox manager | – |
| `postgres` | PostgreSQL 17: users, problems, tags, testcase metadata, submissions | – |
| `redis` | Job queue, warm-container pool, pub/sub, worker heartbeats | – |
| `minio` | S3-compatible object storage for testcase files and submitted code | – |

### Life of a submission

1. The client sends `POST /submissions/` with the code, language and problem ID.
2. The API uploads the code to MinIO, inserts a submission row with verdict `PD` (pending), pushes the submission ID onto the Redis job queue, and responds immediately.
3. A judge worker pops the ID from the queue and records it in its "current submission" slot, so the orchestrator can recover it if the worker dies.
4. The worker takes a ready container from the warm pool and publishes a signal so the sandbox manager creates a replacement.
5. It copies the code into the container, compiles it (C/C++), and runs it against every testcase, measuring time and memory, killing it at the time limit.
6. The output is compared with the expected output (whitespace-insensitive). The first failure decides the verdict.
7. The verdict, runtime, memory and failing testcase are written to PostgreSQL. The client polls `GET /submissions/{id}` until the verdict is no longer `PD`.

---

## Tech stack

| Technology | What it's used for |
|---|---|
| **Python 3.12+** | Both the API and the judge |
| **FastAPI + Uvicorn** | REST API, request validation, auto-generated Swagger docs |
| **Pydantic** | Request/response schemas and input validation |
| **SQLAlchemy + psycopg2** | ORM and PostgreSQL driver |
| **PostgreSQL 17** | Relational database |
| **Redis** | Job queue (`LPUSH`/`BRPOP`), warm-container pool, pub/sub, heartbeats, retry counters |
| **MinIO + boto3** | S3-compatible object storage, accessed with the standard AWS S3 client |
| **Docker + Docker SDK for Python** | Sandboxed code execution |
| **PyJWT + pwdlib (Argon2)** | Authentication tokens and password hashing |
| **multiprocessing / threading** | Parallel judge workers and container creators |
| **nginx** | Serves the frontend and reverse-proxies the API |
| **HTML, CSS, vanilla JavaScript** | Frontend (no framework, no build step) |
| **uv** | Dependency management (`pyproject.toml`, `uv.lock`) |
| **pytest** | Automated tests |

---

## Quick start

Full step-by-step instructions, including a guided test of every feature, are in **[SETUP.md](SETUP.md)**. The short version:

### Prerequisites

- Docker Desktop (or Docker Engine + Compose v2), running
- Git
- *(tests / local development only)* Python 3.12+ and [uv](https://docs.astral.sh/uv/)

### Steps

```bash
# 1. Settings
cp .env.example .env            # change SECRET_KEY for anything beyond local use

# 2. Docker volumes (one time)
docker volume create bytebattles_postgres
docker volume create bytebattles_minio

# 3. Sandbox images for user code (one time)
cd judge/images && sh build_command.sh && cd ../..

# 4. Start everything
docker compose up --build -d

# 5. Storage buckets (one time)
docker compose exec minio sh -c 'mc alias set local http://localhost:9000 minioadmin minioadmin && mc mb --ignore-existing local/bytebattles-testcases local/bytebattles-submission-code'
```

The first build takes a few minutes, because MinIO is compiled from source (see [What was changed](#infrastructure)).

### Create the first admin (one time)

Register an account at `http://localhost:3000` (or `POST /auth/register`), then promote it:

```bash
docker compose exec postgres psql -U postgres -d postgres \
  -c "UPDATE users SET user_type='ADMIN', is_verified=true WHERE username='your_username';"
```

Only the first admin needs this. After that, admins promote other users from the **Admin** page or with `PATCH /users/{username}/role`.

### Addresses

| What | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |

### Stop / reset

```bash
docker compose down                                          # stop, data kept
docker volume rm bytebattles_postgres bytebattles_minio      # wipe all data
```

---

## Using the app

| Page | What you can do |
|---|---|
| **Problems** | Browse problems with difficulty, tags and accepted count |
| **Problem** | Read the statement and examples, write code (templates for Python, C++, C), submit, and watch the verdict update live, including the failing input or compiler errors |
| **My Submissions** | Your full history, filterable by problem. Open any submission to see its code and result |
| **Profile** | Solved problems, recent submissions, and account settings |
| **Admin** | Create tags, create and edit problems (with testcase zip upload), show/hide, rejudge, delete, promote or demote users |

### Testcase zip format

The folder inside the zip must have the **same name as the zip file**, with matching file names in `inputs/` and `outputs/`:

```text
tests.zip
└── tests/
    ├── inputs/   1.txt  2.txt ...
    └── outputs/  1.txt  2.txt ...
```

Tags must exist before a problem can use them. Create them first on the Admin page (or with `POST /problems/tag`).

---

## API overview

Interactive docs: `http://localhost:8000/docs`. Click **Authorize** to log in from Swagger.

### Authentication
| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/auth/register` | public | Create an account |
| POST | `/auth/login` | public | Form login (`username` or email + `password`). Returns access and refresh tokens |
| POST | `/auth/refresh` | public | Exchange a refresh token for a new access token |

### Users
| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/users/me` | logged in | Your profile |
| PATCH | `/users/me` | logged in | Update username, email or password |
| DELETE | `/users/me` | logged in | Delete your account |
| GET | `/users/{username}` | public | Public profile (verified users, or yourself) |
| GET | `/users/{username}/submissions` | public | A user's submissions on visible problems (paginated) |
| GET | `/users/{username}/solved_problems` | public | Visible problems the user has solved |
| PATCH | `/users/{username}/role` | admin | Set `user_type` to `ADMIN` or `USER` (not your own) |

### Problems
| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/problems/` | public | List problems (admins also see hidden ones) |
| GET | `/problems/{problem_id}` | public | Problem details |
| POST | `/problems/tag` | admin | Create a tag (`name`, `slug`) |
| POST | `/problems/` | admin | Create a problem (multipart form + testcase zip) |
| PATCH | `/problems/{problem_id}` | admin | Partially update a problem, including tags and visibility |
| DELETE | `/problems/{problem_id}` | admin | Delete a problem, its testcases and its submissions |
| POST | `/problems/{problem_id}/rejudge` | admin | Reset and re-queue every submission of a problem |

### Submissions
| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/submissions/` | logged in | Submit code (`problem_id`, `language`: `C` / `CPP` / `PY`, `code`) |
| GET | `/submissions/` | public* | List submissions (`problem_id`, `username` filters). *Anonymous callers must pass `username` |
| GET | `/submissions/{submission_id}` | public | Submission details, code and verdict |

`docs/endpoints.md` tracks the endpoint plan, and `docs/openapi.json` is the machine-readable spec.

---

## Verdicts

| Code | Meaning |
|---|---|
| `AC` | Accepted |
| `WA` | Wrong Answer |
| `TLE` | Time Limit Exceeded |
| `MLE` | Memory Limit Exceeded |
| `CE` | Compilation Error |
| `RE` | Runtime Error |
| `PD` | Pending |
| `SKP` | Skipped: the judge gave up after `MAX_JUDGE_ATTEMPTS` internal failures, or the submission's data was invalid |

---

## How the judge works

### Judge orchestrator (`judge/run.py`)
1. Spawns one instance of the sandbox manager.
2. Loops with a 2-second interval.
3. Health-checks every worker using Redis heartbeats, and kills and replaces dead or frozen ones. A frozen worker's submission is re-queued.
4. Computes the desired worker count from the queue length: `min(max_workers, max(min_workers, queue_length // 5 + 1))`.
5. Creates or destroys judge workers to match.
6. Manages the state of each worker in Redis.
7. Handles startup and graceful shutdown of the whole judge system.

### Judge worker (`judge/judge_worker/`)
1. Pops a submission ID from the job queue.
2. Fetches the submission, the time/memory limits and the testcase metadata from PostgreSQL.
3. Pops a ready container from the warm pool (`warm:<language>`).
4. Publishes a pub/sub signal so the sandbox manager replenishes the pool.
5. Fetches the source code from MinIO and copies it into the container.
6. Compiles it (`gcc` / `g++ -O2 -static`) for C and C++.
7. For each testcase: fetches input and expected output from MinIO, runs the program under `/usr/bin/time` and `timeout`, sends the input on stdin, and closes stdin so the program sees end-of-input.
8. Computes the verdict. The first failing testcase stops the run.
9. Writes the result to PostgreSQL and keeps the problem's accepted counter in sync.
10. On errors: pool starvation is re-queued without penalty, invalid data is marked `SKP` immediately, and other failures are retried up to `MAX_JUDGE_ATTEMPTS` times before being marked `SKP`.

### Sandbox manager (`judge/sandbox_manager/main.py`)
1. Spawns a fixed number of creator threads.
2. Fills the pool with `CONTAINER_POOL_THRESHOLD` containers per language.
3. Listens for pub/sub signals from judge workers.
4. Queues creation tasks for the creator threads.
5. A creator thread starts a container, health-checks it, and pushes its ID onto the Redis pool.

### Why this architecture
- Low latency, because containers are pre-warmed
- Better throughput under burst load, because the queue absorbs spikes
- Simple horizontal scaling with more workers
- Clean separation between API, storage and execution
- Safer execution through Docker isolation

### Performance notes
The judge was benchmarked under high load and was able to saturate all available CPU cores on the host machine. This confirmed that the architecture is CPU-bound rather than queue-bound or storage-bound in the tested setup.

---

## What was changed in this version

The codebase was received in a partially stripped-down state: tag creation had been removed, there was no way to promote admins, several planned endpoints were missing, and there were correctness bugs in both the API and the judge. As a result, **no problem could be created at all**, because problem creation requires existing tags. This version restores the full workflow end to end.

### New features

| Feature | Endpoint | Code |
|---|---|---|
| Tag creation (admin only, slug validation, `409` on duplicates) | `POST /problems/tag` | `api/app/routes/problems.py` (`create_tag`), `api/app/schemas/problems.py` (`TagCreate`) |
| Promote / demote users (admin only, cannot change own role, so at least one admin always remains) | `PATCH /users/{username}/role` | `api/app/routes/users.py` (`update_user_role`) |
| Edit a problem (partial update, tag validation, required fields can't be cleared) | `PATCH /problems/{problem_id}` | `api/app/routes/problems.py` (`update_problem`) |
| Delete a problem by ID (also removes testcases and submitted code from storage) | `DELETE /problems/{problem_id}` | `api/app/routes/problems.py` (`delete_problem`) |
| Rejudge a problem (reset verdicts and counters, re-queue every submission) | `POST /problems/{problem_id}/rejudge` | `api/app/routes/problems.py` (`rejudge_problem`) |
| A user's submission history | `GET /users/{username}/submissions` | `api/app/routes/users.py` (`get_user_submissions`) |
| A user's solved problems | `GET /users/{username}/solved_problems` | `api/app/routes/users.py` (`get_user_solved_problems`) |
| Bounded judge retries with a `SKP` verdict | – | `judge/judge_worker/worker.py`, `MAX_JUDGE_ATTEMPTS` in `config.py` |
| Web frontend | – | `frontend/`, `infra/frontend/nginx.conf` |

### Bug fixes

| # | Bug | Effect | Fix | Location |
|---|---|---|---|---|
| 1 | The judge never closed stdin after sending testcase input | Programs reading until end-of-input (`while (cin >> x)`, `sys.stdin.read()`) hung and got a **false TLE** | Half-close the socket (`shutdown(SHUT_WR)`) after sending input | `judge/judge_worker/executor.py` |
| 2 | GNU `time` reports seconds, but the value was stored as milliseconds | Most runtimes showed **0 ms** | Convert to ms, and parse the output robustly (`parse_time_stats`) | `judge/judge_worker/executor.py` |
| 3 | Fragile parsing of `time` output | Unexpected stderr crashed the worker and caused endless retries | Robust parser that raises a clear error | `judge/judge_worker/executor.py` |
| 4 | `offset = page * limit` in the problem list | **Page 1 skipped the first 20 problems** | `offset = (page - 1) * limit` | `api/app/routes/problems.py` |
| 5 | Refresh token created with the access-token lifetime | Refresh tokens expired after **30 minutes instead of 7 days** | Use `REFRESH_TOKEN_EXPIRE_DAYS` | `api/app/utils/oauth2.py` |
| 6 | Public profile response missing the required `is_verified` field | Viewing another user's profile returned **500** | Pass the field | `api/app/routes/users.py` |
| 7 | Failing testcase looked up in the submission-code bucket | The failing input was **never shown** | Look it up in the testcases bucket | `shared/models/submission.py` |
| 8 | `accepted_submissions` / `total_submissions` never updated | Counters always **0** | Atomic increments. The accepted count follows verdict transitions, so rejudging never double-counts | `api/app/routes/submissions.py`, `judge/judge_worker/pipeline.py` |
| 9 | A problem with zero testcases | Marked **AC** without running anything | Rejected as invalid data | `judge/judge_worker/pipeline.py` |
| 10 | Unbounded retry loop in the worker | One bad submission could **loop forever**, and some errors left submissions stuck at `PD` | Retry cap plus `SKP` verdict. Pool starvation doesn't count as an attempt | `judge/judge_worker/worker.py` |
| 11 | Error handler referenced a possibly undefined variable | The error handler itself could crash | Initialise and check `submission_id` | `judge/judge_worker/worker.py` |
| 12 | `upload_file` used an undefined `file` variable, and folder deletes were capped at 1000 objects | Crash when called, and leftover files for large problems | `file` parameter added, and deletes paginated | `shared/core/storage.py` |
| 13 | Logger assumed the `logs/` directory existed | The judge crashed when run locally without it | Create the directory automatically | `judge/utils.py` |

Smaller clean-ups:
- A bare `except:` in optional auth was narrowed to `except HTTPException:`.
- An unused module-level Redis client was removed.
- Boolean column defaults use SQLAlchemy's portable `false()`.
- `config.py` accepts an optional `DB_URL` override.

### Infrastructure

| Change | Why |
|---|---|
| MinIO is **built from source** (`infra/minio/Dockerfile`) instead of pulling `minio/minio` | MinIO stopped publishing community images. `minio/minio` no longer exists on Docker Hub. The image also includes the `mc` client, used to create the buckets |
| PostgreSQL pinned to **`postgres:17`** | PostgreSQL 18+ images changed the data-directory layout and refuse to start with the existing volume mount |
| New `frontend` service (nginx on port 3000) | Serves the web UI and proxies `/api/*` to FastAPI, so the browser uses a single origin and no CORS configuration is needed |
| `.gitignore` added | Keeps `.env`, virtualenvs, caches and logs out of git |
| `pytest` / `httpx` added to a `dev` dependency group | For the test suite |

### Documentation
- `SETUP.md` rewritten as a complete setup and feature-testing guide.
- `docs/endpoints.md` updated, and `docs/openapi.json` regenerated.
- This README.

---

## Testing

### Automated tests

```bash
uv sync --group api --group judge --group dev
uv run pytest -v
```

28 tests cover every new endpoint, every bug fix, and the judge's retry logic. They run in a few seconds **without Docker or any running service**. PostgreSQL is replaced by SQLite, and MinIO and Redis by in-memory fakes (see `tests/conftest.py`).

| File | Covers |
|---|---|
| `tests/test_api.py` | Auth and refresh tokens, tags, problem create/list/edit/delete/rejudge, submissions and counters, profiles, roles |
| `tests/test_judge.py` | Time/memory parsing, output comparison, accepted-counter transitions, empty testcases, worker retry and skip behaviour |

### End-to-end check

With the stack running, submit these to a simple "add two numbers" problem. Each should get the listed verdict:

| Code | Verdict |
|---|---|
| Correct solution (Python, C or C++) | AC |
| `print(0)` | WA |
| `while True: pass` | TLE |
| `raise Exception("boom")` | RE |
| C++ with a syntax error | CE |
| Python reading with `sys.stdin.read()` / C++ `while (cin >> x)` | AC (this previously gave a false TLE) |

[SETUP.md](SETUP.md), Part C, walks through testing every feature step by step in the browser.

---

## Configuration

All settings come from `.env` (template: `.env.example`), loaded by `config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | `redis`, `6379`, `0` | Redis connection |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWD`, `DB_DATABASE` | `postgres`, `5432`, … | PostgreSQL connection |
| `DB_URL` | *(unset)* | Optional full SQLAlchemy URL that overrides the above |
| `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_SIGNATURE_VERSION` | `http://minio:9000`, `minioadmin`, `minioadmin`, … | Object storage. To use AWS S3, set an IAM user's keys and the AWS endpoint, with no code changes |
| `TESTCASE_BUCKET`, `SUBMISSION_BUCKET` | `bytebattles-testcases`, `bytebattles-submission-code` | Bucket names |
| `SECRET_KEY`, `ALGORITHM` | – , `HS256` | JWT signing. **Change `SECRET_KEY`** |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | `30`, `7` | Token lifetimes |
| `CONTAINER_POOL_THRESHOLD`, `CONTAINER_WORKER_COUNT` | `10`, `4` | Warm containers per language, and creator threads |
| `MAX_MEMCAP_GB`, `MAX_PIDS` | `1`, `64` | Hard limits per sandbox container |
| `ACQUIRE_TIMEOUT_SECONDS` | `10` | How long a worker waits for a warm container |
| `MINIMUM_JUDGE_WORKER`, `MAXIMUM_JUDGE_WORKER` | `4`, `20` | Autoscaling bounds |
| `JUDGE_WORKER_TIMEOUT` | `120` | Seconds without a heartbeat before a worker is considered frozen |
| `MAX_JUDGE_ATTEMPTS` | `3` | Internal failures before a submission is marked `SKP` |

---

## Repository layout

```text
ByteBattles/
├── README.md
├── SETUP.md                     # Setup + step-by-step feature testing
├── config.py                    # Loads .env into constants
├── .env.example
├── docker-compose.yaml          # frontend, api, judge, postgres, redis, minio
├── pyproject.toml / uv.lock     # Dependencies (uv groups: api, judge, dev)
│
├── api/
│   ├── Dockerfile
│   └── app/
│       ├── main.py              # FastAPI app, routers, table creation
│       ├── database.py          # get_db() dependency
│       ├── routes/              # auth, users, problems, submissions
│       ├── schemas/             # Pydantic request/response models
│       └── utils/               # oauth2 (JWT), password hashing, Redis enqueue
│
├── judge/
│   ├── Dockerfile
│   ├── run.py                   # Orchestrator entry point
│   ├── utils.py                 # Logging
│   ├── judge_worker/            # worker loop, pipeline, executor, queues, storage
│   ├── sandbox_manager/         # warm container pool
│   └── images/                  # judge-gcc and judge-python sandbox images
│
├── shared/
│   ├── core/                    # SQLAlchemy engine/session, S3 storage
│   └── models/                  # User, Problem, Category/Tag, TestCase, Submission, enums
│
├── frontend/                    # Web UI (HTML, CSS, vanilla JS)
│   ├── *.html                   # problems, problem, submissions, submission, profile, admin, login, register
│   ├── css/style.css
│   └── js/                      # api.js (API client), common.js, pages/*.js
│
├── infra/
│   ├── minio/Dockerfile         # MinIO + mc built from source
│   └── frontend/nginx.conf      # Static files + /api reverse proxy
│
├── tests/                       # pytest suite
│
└── docs/
    ├── endpoints.md
    ├── openapi.json
    └── Judge_Architecture.pdf
```

---

## Security model

Submitted code is untrusted. Each sandbox container runs with:
- all Linux capabilities dropped
- networking disabled
- `no-new-privileges`
- memory and PID limits
- an unprivileged `run` user
- single use: a container is stopped and removed after judging one submission

On the API side, passwords are stored as Argon2 hashes, login is protected against username-enumeration timing attacks, and admin endpoints are enforced server-side.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `volume bytebattles_postgres not found` | `docker volume create bytebattles_postgres` (and `bytebattles_minio`) |
| Submissions stay **Pending** | Check `docker compose ps` and `docker compose logs judge` |
| `No such image: judge-gcc` | Build the sandbox images: `cd judge/images && sh build_command.sh` |
| "Unknown Error Occurred" when creating a problem | Buckets not created, or problem ID longer than 6 characters |
| "ZIP must contain inputs/ and outputs/" | The folder inside the zip must match the zip's filename |
| "One or more tags are invalid" | Create the tag first (Admin page or `POST /problems/tag`) |
| "Not enough permissions" | The account isn't an admin (see [Create the first admin](#create-the-first-admin-one-time)) |
| Can't submit to a problem | It's hidden. Use **Show** on the Admin page |
| A user's profile returns 404 | The user isn't verified yet (there's no email verification flow) |

Logs are also written to `./logs/` (`orchestrator.log`, `sandbox.log`, `worker_*.log`).

---

## Known limitations and future improvements

- Per-problem memory limits are measured (peak RSS) rather than hard-enforced. Containers share a flat `MAX_MEMCAP_GB` cap.
- No email verification flow yet (`is_verified` is set manually).
- No database migrations yet (tables are created on API startup). Alembic would be the next step.
- A rejudge can race with a submission that's being judged at that moment.
- Redis Streams for stronger job-recovery semantics
- Distributed judge nodes
- More advanced output checking (special judges)
- Container runtime alternatives such as nsjail, minijail or gVisor

---

## Project goals

ByteBattles is intended to be more than a CRUD application. It is a systems-heavy project focused on:
- distributed execution
- sandboxing
- queue-based orchestration
- low-latency worker design
- scalable backend architecture

---

## License

Copyright - 2026 - DIPANSHU TIWARI

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

Built for learning, systems engineering, and competitive programming infrastructure.
