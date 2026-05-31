#!/usr/bin/env python3
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "litellm.env"
EXPECTED_TABLES = (
    "LiteLLM_UserTable",
    "LiteLLM_VerificationToken",
    "LiteLLM_SpendLogs",
    "LiteLLM_DailyUserSpend",
    "LiteLLM_DailyTagSpend",
    "LiteLLM_DailyTeamSpend",
)


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip("'\""))


def get(path: str, auth: bool = False) -> tuple[int, str]:
    base_url = os.getenv("LITELLM_HEALTH_URL", "http://localhost:4000").rstrip("/")
    master_key = os.getenv("LITELLM_MASTER_KEY", "")
    headers = {}
    if auth and master_key:
        headers["Authorization"] = f"Bearer {master_key}"

    request = Request(f"{base_url}{path}", headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.status, response.read().decode("utf-8")


def check_supabase_tables() -> bool:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        print("[FAIL] LiteLLM tables: DATABASE_URL is not set")
        return False

    if shutil.which("psql") is None:
        print("[SKIP] LiteLLM tables: psql is not installed")
        return True

    table_names = ",".join(f"'{table}'" for table in EXPECTED_TABLES)
    query = (
        "select table_name from information_schema.tables "
        f"where table_schema = 'public' and table_name in ({table_names}) "
        "order by table_name;"
    )
    command = ["psql", database_url, "-Atc", query]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        redacted = shlex.join(["psql", "$DATABASE_URL", "-Atc", query])
        print(f"[FAIL] LiteLLM tables: {exc} while running {redacted}")
        return False

    found = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    missing = sorted(set(EXPECTED_TABLES) - found)
    if missing:
        print(f"[FAIL] LiteLLM tables: missing {', '.join(missing)}")
        return False

    print("[OK] LiteLLM tables: found expected tables in Supabase/Postgres")
    return True


def main() -> int:
    load_env_file()

    checks = [
        ("proxy health", "/health", True),
        ("readiness and database", "/health/readiness", False),
        ("user table API", "/user/list", True),
        ("key table API", "/key/list", True),
    ]

    failed = False
    for name, path, auth in checks:
        try:
            status_code, body = get(path, auth=auth)
        except HTTPError as exc:
            print(f"[FAIL] {name}: HTTP {exc.code} {exc.reason}")
            failed = True
            continue
        except URLError as exc:
            print(f"[FAIL] {name}: {exc}")
            failed = True
            continue
        except Exception as exc:
            print(f"[FAIL] {name}: {exc}")
            failed = True
            continue

        print(f"[OK] {name}: HTTP {status_code}")
        if path == "/health/readiness":
            import json

            readiness = json.loads(body)
            db_status = readiness.get("db")
            if db_status != "connected":
                print(f"[FAIL] readiness and database: db={db_status!r}")
                failed = True
            else:
                print("[OK] Supabase/Postgres database: connected")

    if not check_supabase_tables():
        failed = True

    if failed:
        return 1

    print("LiteLLM health checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
