"""Checks the mounted Scriba checkout before the api container serves or tests.

Run by backend/Dockerfile.seeded before the server and the tests start:

- the checkout is there (SCRIBA_BACKEND_PATH has e2e/seeded_server.py);
- Scriba's requirements.txt is the one the image was built with. If Scriba
  was pulled after the build, its code and the installed packages may not
  match: this stops with "run docker compose build api".
- the checkout is at the revision this repository was tested against
  (backend/SCRIBA_REVISION). A different revision is reported, not refused.

Uses no git binary: it reads the checkout's .git directory, mounted at
SCRIBA_REPO_PATH (the parent of Scriba's Gmail/ directory).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PIN_FILE = BACKEND / "SCRIBA_REVISION"
BUILT_REQUIREMENTS = Path("/etc/scriba-requirements.sha256")


def fail(message: str) -> None:
    sys.exit(f"[scriba-check] {message}")


def note(message: str) -> None:
    print(f"[scriba-check] {message}", flush=True)


def head_revision(repo: Path) -> str | None:
    """The commit HEAD points at, read from .git without the git binary."""
    git = repo / ".git"
    if not git.is_dir():  # missing, or a worktree's .git file pointing at a host path
        return None
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    loose = git / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def main() -> None:
    scriba = Path(os.environ.get("SCRIBA_BACKEND_PATH", "/scriba"))
    if not (scriba / "e2e" / "seeded_server.py").is_file():
        fail(
            f"No Scriba checkout at {scriba}. Clone it next to this repository "
            "(git clone https://github.com/ScribaAssist/Scriba ../scriba) or set "
            "SCRIBA_PATH to a checkout's Gmail/ directory, then docker compose up -d again."
        )

    if BUILT_REQUIREMENTS.is_file():
        built = BUILT_REQUIREMENTS.read_text(encoding="utf-8").strip()
        current = hashlib.sha256((scriba / "requirements.txt").read_bytes()).hexdigest()
        if built != current:
            fail(
                "Scriba's requirements.txt changed since this image was built, so its code "
                "and the installed packages may not match. Run: docker compose build api"
            )

    pinned = PIN_FILE.read_text(encoding="utf-8").strip() if PIN_FILE.is_file() else ""
    repo = os.environ.get("SCRIBA_REPO_PATH", "").strip()
    actual = head_revision(Path(repo)) if repo else None
    if not pinned:
        return
    if actual is None:
        note(f"Could not read the checkout's revision; this repository is tested against {pinned[:10]}.")
    elif actual != pinned:
        note(
            f"Scriba checkout is at {actual[:10]}, but this repository is tested against "
            f"{pinned[:10]} (backend/SCRIBA_REVISION). To match: "
            f"git -C ../scriba checkout {pinned[:10]}. After testing a newer revision, "
            "update backend/SCRIBA_REVISION."
        )
    else:
        note(f"Scriba checkout at the pinned revision {pinned[:10]}.")


if __name__ == "__main__":
    main()
