"""Integration tests run against a real Scriba checkout, hermetically.

They are skipped unless SCRIBA_BACKEND_PATH names the ``Gmail/`` directory of
a Scriba checkout. The environment below mirrors Scriba's own test bootstrap
(``tests/conftest.py``): a developer's ``.env`` is never loaded, the database
URL is a dummy, and no provider is reachable.
"""
import os
import sys
from pathlib import Path

import pytest

SCRIBA = os.environ.get("SCRIBA_BACKEND_PATH", "").strip()
AVAILABLE = bool(SCRIBA) and (Path(SCRIBA) / "app" / "main.py").is_file()

collect_ignore_glob = [] if AVAILABLE else ["test_*.py"]

if AVAILABLE:
    try:
        import dotenv

        # Never inherit local provider credentials or a real database URL.
        dotenv.load_dotenv = lambda *args, **kwargs: False
    except ImportError:
        pass
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/scriba_test?sslmode=disable")
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("DB_POOL_MIN", "0")
    os.environ.setdefault("DB_POOL_TIMEOUT", "2")
    os.environ.setdefault("GMAIL_RECONCILE_ENABLED", "false")
    os.environ.setdefault("CHAT_ANSWER_PASS", "off")
    os.environ.setdefault("AGENT_RELEASE_BACKGROUND_REFRESH", "false")
    for path in (SCRIBA, str(Path(SCRIBA) / "tests")):
        if path not in sys.path:
            sys.path.insert(0, path)


@pytest.fixture(scope="session")
def scriba_path() -> Path:
    return Path(SCRIBA)
