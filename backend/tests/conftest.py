import os
import tempfile


# Set this before any test module imports the application's database settings.
# One SQLite file per test run: several checkouts' test runs (or agents) may
# run at once, and a shared ./test.db lets one run drop another's tables.
TEST_DATABASE_URL = f"sqlite:///{tempfile.gettempdir()}/nexus-novel-test-{os.getpid()}.db"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Test fixtures build their schema with create_all; migrations have their own
# tests (tests/database/test_migrations.py).
os.environ["RUN_MIGRATIONS_ON_STARTUP"] = "false"


def pytest_sessionfinish(session, exitstatus):
    path = TEST_DATABASE_URL.removeprefix("sqlite:///")
    if os.path.exists(path):
        os.remove(path)
