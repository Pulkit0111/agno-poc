# tests/test_github_write.py
import subprocess

from bott.agents.code_review.github.clone import writable_clone


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def test_writable_clone_sets_identity_and_is_a_repo(monkeypatch, tmp_path):
    # Build a local origin repo to clone (no network).
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    (work / "a.txt").write_text("hi")
    _git(["config", "user.email", "t@t"], work)
    _git(["config", "user.name", "t"], work)
    _git(["add", "."], work)
    _git(["commit", "-qm", "init"], work)
    _git(["branch", "-M", "main"], work)
    _git(["remote", "add", "origin", str(origin)], work)
    _git(["push", "-q", "origin", "main"], work)

    # Patch the clone URL builder to point at our local bare repo.
    import bott.agents.code_review.github.clone as clone_mod
    monkeypatch.setattr(clone_mod, "_clone_url", lambda owner, name, token: str(origin))

    with writable_clone("o", "r", token="x") as h:
        assert (subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                               cwd=h.path, capture_output=True, text=True).stdout.strip() == "true")
        name = _git(["config", "user.name"], h.path).stdout.strip()
        assert name == "bott"  # the bot identity was actually written (not the global default)
