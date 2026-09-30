# ByteBattles — Setup & Testing Guide

This guide takes you from a fresh clone to a working app, then walks through testing every feature step by step. Part C is written so you can follow it while recording a demo.

- **Part A** – What the task was and what we did (short version)
- **Part B** – Setup: get the app running
- **Part C** – Test it step by step in the website (demo script)
- **Part D** – Automated tests
- **Part E** – Everyday commands, running outside Docker, troubleshooting

---

## Part A — The task, in short

**What ByteBattles is:** the backend of a coding-practice site like LeetCode. Admins publish problems with hidden testcases. Users submit C, C++ or Python code, and a "judge" runs it safely inside Docker containers and gives a verdict (Accepted, Wrong Answer, Time Limit Exceeded, …).

**The problem statement:** the project was handed over with pieces deliberately removed, and was not working end to end:

1. **Tag creation had been removed.** Every problem needs tags, so no problem could be created at all.
2. **There was no way to make someone an admin** except editing the database by hand.
3. **Several planned features were missing:** edit / delete / rejudge a problem, and a user's submission history and solved list.
4. **The existing code had bugs.** For example, page 1 of the problem list skipped problems, logins expired far too early, viewing a profile crashed, and the judge gave wrong "Time Limit Exceeded" verdicts to correct programs.

(The written brief, `PROBLEM_STATEMENT.md`, was never included in the repo. The task above comes from notes in the code and `docs/endpoints.md`.)

**What we did:**

- Added the missing features: tag creation, admin promotion, edit/delete/rejudge problem, user submissions and solved problems.
- Fixed 13 bugs in the API and the judge.
- Added 28 automated tests.
- Made the app start again: MinIO's Docker image had disappeared (so we build it locally), and Postgres is pinned to version 17.
- Built a simple website (plain HTML/CSS/JS) at `http://localhost:3000`, so everything can be used without typing commands.
- Verified every verdict end to end with real code in real containers.

---

## Part B — Setup

### B0. What you need installed

| Tool | Check it works |
|---|---|
| Docker Desktop (running!) | `docker info` prints details, not an error |
| Git | `git --version` |
| *(only for Part D)* Python 3.12+ and `uv` | `python3 --version`, `uv --version` |

### B1. Get the code

```bash
git clone <repo-url> ByteBattles
cd ByteBattles
git checkout complete-platform
```

All commands below are run from the `ByteBattles` folder.

### B2. Create the settings file

```bash
cp .env.example .env
```

The defaults work for local use. If anyone else will use this setup, change `SECRET_KEY` to a long random value (`openssl rand -hex 32`), and change the passwords.

### B3. Create the storage volumes (one time)

```bash
docker volume create bytebattles_postgres
docker volume create bytebattles_minio
```

### B4. Build the code-runner images (one time)

These are the locked-down containers that user code runs in:

```bash
cd judge/images
sh build_command.sh
cd ../..
```

Check: `docker images | grep judge-` shows `judge-gcc` and `judge-python`.

### B5. Start everything

```bash
docker compose up --build -d
```

The first run takes several minutes, because it builds MinIO from source and the API/judge images. It starts 6 services:

| Service | What it is | Address |
|---|---|---|
| `frontend` | The website | **http://localhost:3000** |
| `api` | The backend (FastAPI) | http://localhost:8000/docs |
| `judge` | Runs submitted code | – |
| `postgres` | Database (v17) | – |
| `redis` | Job queue | – |
| `minio` | File storage (testcases, code) | – |

Check that all are up:

```bash
docker compose ps
```

### B6. Create the storage buckets (one time)

```bash
docker compose exec minio sh -c 'mc alias set local http://localhost:9000 minioadmin minioadmin && mc mb --ignore-existing local/bytebattles-testcases local/bytebattles-submission-code'
```

If you changed `S3_ACCESS_KEY` / `S3_SECRET_KEY` in `.env`, use those values instead of `minioadmin minioadmin`.

### B7. Create the first admin (one time)

1. Open **http://localhost:3000** → **Register** → create an account, e.g. `admin` / `password123`.
2. Make it an admin, and verified, from the terminal:

```bash
docker compose exec postgres psql -U postgres -d postgres \
  -c "UPDATE users SET user_type='ADMIN', is_verified=true WHERE username='admin';"
```

This database step is only needed for the **first** admin. After that, admins promote other users from the Admin page.

The app is now ready.

---

## Part C — Test it step by step (demo script)

Everything here happens in the browser at **http://localhost:3000**. Each step says what to do and what you should see.

### C1. Prepare a testcase zip (do this before recording)

A problem needs a zip of hidden testcases. **The folder inside the zip must have the same name as the zip file.** Create one in the terminal:

```bash
mkdir -p ~/Desktop/tests/inputs ~/Desktop/tests/outputs
printf "1 2\n"   > ~/Desktop/tests/inputs/1.txt
printf "3\n"     > ~/Desktop/tests/outputs/1.txt
printf "10 20\n" > ~/Desktop/tests/inputs/2.txt
printf "30\n"    > ~/Desktop/tests/outputs/2.txt
cd ~/Desktop && zip -r tests.zip tests -x "*.DS_Store" && cd -
```

You now have `~/Desktop/tests.zip`: two testcases for "add two numbers". (Using the terminal avoids macOS adding hidden `.DS_Store` files, which would break the upload.)

### C2. Log in as admin

1. Click **Log in**, then enter `admin` / `password123`.
2. ✅ The top-right shows your username and **Log out**.

### C3. Create a tag (feature we added)

1. Click **Admin**.
2. Under **Create a tag**, type the name `Math`. The slug fills in as `math`.
3. Click **Create tag**.
4. ✅ Green message: *Created tag "Math" (slug: math)*.
5. *(Optional)* Click it again → red message: *Tag with this slug already exists*. Duplicates are rejected.

### C4. Create a problem

1. On the Admin page, click **+ New problem**.
2. Fill in:
   - Problem ID: `ADD2` (max 6 characters)
   - Title: `Add Two Numbers`
   - Tags: `math`
   - Description: `Read two integers and print their sum.`
   - Input format: `Two integers a and b.`
   - Output format: `Their sum.`
   - Constraints: `1 <= a, b <= 1000`
   - Example: input `1 2`, output `3`
   - Leave **Visible to users** unticked for now.
   - Testcases: choose `tests.zip`
3. Click **Create problem**.
4. ✅ *Created ADD2 with 2 testcase(s).* ADD2 appears in the table as **Hidden**.

### C5. Show / hide a problem (feature we added)

1. Click **Show** on ADD2. ✅ Its Visible column says **Yes**.
2. Click **Problems** in the top bar. ✅ ADD2 is in the list.

### C6. Submit a correct solution → Accepted

1. Open **ADD2**. You see the description, limits and example.
2. Language **Python 3**. The editor already has a template that adds two numbers.
3. Click **Submit**.
4. ✅ A spinner shows *Pending*, then within a couple of seconds a green **Accepted** with time and memory.

### C7. Show every verdict

Submit each of these on ADD2 (clear the editor, paste, then Submit):

| Language | Code | Expected verdict |
|---|---|---|
| Python 3 | `print(0)` | 🔴 **Wrong Answer** (shows the failing input and your output) |
| Python 3 | `while True: pass` | 🟠 **Time Limit Exceeded** |
| Python 3 | `raise Exception("boom")` | 🔴 **Runtime Error** |
| C++ | `int main( { return 0 }` | 🔴 **Compilation Error** (shows the compiler message) |
| C++ | the default C++ template | 🟢 **Accepted** |
| Python 3 | `import sys`<br>`a, b = map(int, sys.stdin.read().split())`<br>`print(a + b)` | 🟢 **Accepted** (this used to wrongly give TLE; one of the bugs we fixed) |

Below the editor, **Your submissions for this problem** lists every attempt.

### C8. Submission history and details

1. Click **My Submissions**. ✅ Every submission with verdict, time and memory. Type `ADD2` in the filter to narrow it down.
2. Click any `#number`. ✅ The detail page shows the code, verdict, and failing input where relevant.

### C9. Profile (features we added)

1. Click your username (top right).
2. ✅ **Solved problems** lists ADD2, and **Recent submissions** shows your attempts.
3. **Account settings** at the bottom lets you change username, email or password.

### C10. Promote another user to admin (feature we added)

1. Log out, then **Register** a second user, e.g. `student1` / `password123`.
2. As `student1`, open **Admin** and try **Create tag**. ✅ Red: *Not enough permissions*. Normal users are blocked.
3. Log out, and log in as `admin`.
4. Admin → **User roles**: username `student1`, role **Admin** → **Update role**.
5. ✅ *student1 is now an admin.* If you log in as student1, creating a tag now works.
6. *(Optional)* Try changing `admin`'s own role. ✅ Refused: *Admins cannot change their own role*.

### C11. Edit a problem (feature we added)

1. Admin → **Edit** on ADD2 → change the title to `Sum of Two Numbers` → **Save changes**.
2. ✅ The new title shows in the table and on the problem page.

### C12. Rejudge (feature we added)

1. Admin → **Rejudge** on ADD2 → confirm.
2. ✅ *Requeued N submission(s) of ADD2.* On My Submissions, the verdicts briefly show Pending, then come back with the same results.

### C13. Delete a problem (feature we added)

1. Admin → **Delete** on ADD2 → confirm.
2. ✅ *Deleted ADD2.* It's gone from the Problems list, along with its testcases and submissions.

### C14. (Optional) Show the backend

- **http://localhost:8000/docs**: the API's interactive documentation. Every feature above is an endpoint here.
- `docker ps` while submitting: you can see the pool of ready `sandbox_...` containers the judge uses.
- `docker compose logs -f judge`: watch the judge pick up and grade submissions live.

---

## Part D — Automated tests

28 tests cover the new features and the bug fixes. They don't need Docker or any running service.

```bash
uv sync --group api --group judge --group dev
uv run pytest -v
```

✅ Expected: `28 passed`.

---

## Part E — Everyday commands and troubleshooting

### Start / stop

```bash
docker compose up -d            # start (after the one-time setup)
docker compose down             # stop – your data is kept
docker compose ps               # what's running
docker compose logs -f api      # follow logs (api / judge / frontend / ...)
```

Start completely fresh (**deletes all users, problems and submissions**):

```bash
docker compose down
docker volume rm bytebattles_postgres bytebattles_minio
# then redo B3, B5, B6, B7
```

### Running the API and judge outside Docker (for development)

Compose only publishes ports 3000 and 8000, so first create `docker-compose.dev.yml`:

```yaml
services:
  postgres:
    ports: ["5432:5432"]
  redis:
    ports: ["6379:6379"]
  minio:
    ports: ["9000:9000"]
```

Then:

```bash
# in .env: DB_HOST=localhost, REDIS_HOST=localhost, S3_ENDPOINT_URL=http://localhost:9000
docker compose -f docker-compose.yaml -f docker-compose.dev.yml up -d postgres redis minio
uv sync --group api --group judge --group dev
uv run uvicorn api.app.main:app --reload     # terminal 1
uv run python -m judge.run                   # terminal 2
```

(The website on port 3000 talks to the API inside Docker. When running the API outside Docker, use http://localhost:8000/docs instead.)

### Troubleshooting

| Problem | Fix |
|---|---|
| `volume bytebattles_postgres not found` | Run step B3 |
| Submissions stay **Pending** | Is the judge running? `docker compose ps`, then `docker compose logs judge` |
| Judge log says `No such image: judge-gcc` | Run step B4 |
| "Unknown Error Occurred" when creating a problem | Buckets missing (step B6), or problem ID longer than 6 characters |
| "ZIP must contain inputs/ and outputs/" | The folder inside the zip must match the zip's name (see C1) |
| "One or more tags are invalid" | Create the tag first (C3) |
| "Not enough permissions" | Your account isn't an admin (B7 or C10) |
| Can't submit / problem not found | The problem is hidden. Click **Show** on the Admin page |
| Someone's profile says it doesn't exist | That user isn't verified (there's no email verification yet). Set `is_verified=true` in the database like in B7 |
| Website shows "Could not reach the server" | The `api` service is down: `docker compose up -d` |
| Logs | Also written to `./logs/` (`orchestrator.log`, `sandbox.log`, `worker_*.log`) |
