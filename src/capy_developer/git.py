from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .errors import DeveloperError
from .util import HEX40, normalize_repository


def run_git(arguments: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
    })
    safe_configuration = [
        "-c", "core.fsmonitor=false",
        "-c", "protocol.allow=never",
        "-c", "protocol.file.allow=always",
        "-c", "protocol.http.allow=always",
        "-c", "protocol.https.allow=always",
        "-c", "protocol.ssh.allow=always",
        "-c", "protocol.git.allow=always",
    ]
    completed = subprocess.run(
        ["git", *safe_configuration, *arguments], cwd=cwd, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "Git command failed"
        raise DeveloperError("GIT_FAILED", detail, data={"git_exit": completed.returncode})
    return completed.stdout.strip()


def require_checkout(path: Path) -> None:
    if run_git(["-C", str(path), "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        raise DeveloperError("NOT_GIT_CHECKOUT", "the import path is not a Git working tree")


def checkout_facts(path: Path) -> dict:
    require_checkout(path)
    commit = run_git(["-C", str(path), "rev-parse", "HEAD"])
    branch = run_git(["-C", str(path), "symbolic-ref", "--short", "-q", "HEAD"], check=False) or None
    origin = run_git(["-C", str(path), "remote", "get-url", "origin"], check=False) or None
    scp_remote = origin and re.fullmatch(r"(?:[^@\s]+@)?[^:\s]+:/?[^:\s].*", origin)
    if origin and "://" not in origin and not scp_remote:
        candidate = Path(origin)
        if not candidate.is_absolute():
            origin = (path / candidate).resolve().as_uri()
    status = run_git(["-C", str(path), "status", "--porcelain=v1"])
    return {"commit": commit, "branch": branch, "origin": origin, "dirty": bool(status)}


def remote_default_branch(origin: str, fallback: str | None = None) -> str:
    output = run_git(["ls-remote", "--symref", origin, "HEAD"], check=False)
    for line in output.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line[len("ref: refs/heads/"):].split("\t", 1)[0]
    return fallback or "main"


def ensure_mirror(origin: str, mirror: Path) -> None:
    if mirror.exists():
        if run_git(["--git-dir", str(mirror), "rev-parse", "--is-bare-repository"], check=False) != "true":
            raise DeveloperError("MIRROR_INVALID", "managed mirror path is not a bare Git repository")
        configured = run_git(["--git-dir", str(mirror), "remote", "get-url", "origin"])
        if normalize_repository(configured) != normalize_repository(origin):
            raise DeveloperError("MIRROR_ORIGIN_CONFLICT", "managed mirror origin does not match the project")
        if configured != origin:
            run_git(["--git-dir", str(mirror), "remote", "set-url", "origin", origin])
        run_git(["--git-dir", str(mirror), "fetch", "--prune", "origin"])
        return
    mirror.parent.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--bare", str(mirror)])
    run_git(["--git-dir", str(mirror), "remote", "add", "origin", origin])
    run_git(["--git-dir", str(mirror), "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"])
    run_git(["--git-dir", str(mirror), "fetch", "--prune", "origin"])


def mirror_base(mirror: Path, default_branch: str) -> str:
    commit = run_git(["--git-dir", str(mirror), "rev-parse", f"refs/remotes/origin/{default_branch}"], check=False)
    if not HEX40.fullmatch(commit):
        commit = run_git(["--git-dir", str(mirror), "rev-parse", f"refs/heads/{default_branch}"])
    if HEX40.fullmatch(commit) is None:
        raise DeveloperError("BASE_COMMIT_INVALID", "default branch did not resolve to an exact commit")
    return commit


def ensure_worktree(mirror: Path, path: Path, branch: str, base: str) -> None:
    if path.exists():
        actual = run_git(["-C", str(path), "rev-parse", "HEAD"], check=False)
        actual_branch = run_git(["-C", str(path), "symbolic-ref", "--short", "-q", "HEAD"], check=False)
        if actual != base or actual_branch != branch:
            raise DeveloperError("WORKTREE_CONFLICT", "existing managed worktree does not match the session")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    branch_ref = run_git(["--git-dir", str(mirror), "show-ref", "--verify", f"refs/heads/{branch}"], check=False)
    if branch_ref:
        run_git(["--git-dir", str(mirror), "worktree", "add", str(path), branch])
    else:
        run_git(["--git-dir", str(mirror), "worktree", "add", "-b", branch, str(path), base])


def initialize_bare(path: Path) -> None:
    if path.exists():
        if run_git(["--git-dir", str(path), "rev-parse", "--is-bare-repository"], check=False) != "true":
            raise DeveloperError("CANONICAL_REPOSITORY_CONFLICT", "canonical repository path is not bare Git")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--bare", "--initial-branch=main", str(path)])


def validate_candidate(path: Path, branch: str, candidate: str, base: str) -> dict:
    require_checkout(path)
    status = run_git(["-C", str(path), "status", "--porcelain=v1", "--untracked-files=all"])
    if status:
        raise DeveloperError("WORKTREE_DIRTY", "authoritative verification requires a clean worktree")
    actual_branch = run_git(["-C", str(path), "symbolic-ref", "--short", "-q", "HEAD"], check=False)
    if actual_branch != branch:
        raise DeveloperError("WORKTREE_BRANCH_CHANGED", "managed worktree branch differs from the session")
    actual = run_git(["-C", str(path), "rev-parse", "--verify", "HEAD"], check=False)
    if actual != candidate:
        raise DeveloperError("CANDIDATE_COMMIT_MISMATCH", "worktree HEAD does not equal candidate_commit")
    resolved = run_git(["-C", str(path), "rev-parse", "--verify", f"{candidate}^{{commit}}"], check=False)
    if resolved != candidate:
        raise DeveloperError("CANDIDATE_COMMIT_UNAVAILABLE", "candidate_commit is unavailable in the session repository")
    common = run_git(["-C", str(path), "merge-base", base, candidate], check=False)
    if common != base:
        raise DeveloperError("CANDIDATE_BASE_MISMATCH", "candidate_commit does not descend from the session base")
    for marker in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        marker_path = run_git(["-C", str(path), "rev-parse", "--git-path", marker], check=False)
        if marker_path and Path(marker_path).exists():
            raise DeveloperError("GIT_OPERATION_UNRESOLVED", "managed worktree has an unresolved Git operation")
    tree = run_git(["-C", str(path), "rev-parse", f"{candidate}^{{tree}}"])
    listing = run_git(["-C", str(path), "ls-tree", "-r", candidate])
    if any(line.startswith("160000 ") for line in listing.splitlines()):
        raise DeveloperError("CANDIDATE_GITLINK_UNSUPPORTED", "Git submodules are unsupported for portable V0 verification")
    return {"commit": candidate, "tree": tree, "branch": branch, "base_commit": base}


def add_detached_worktree(repository_worktree: Path, destination: Path, commit: str) -> None:
    if destination.exists():
        raise DeveloperError("VERIFICATION_PATH_CONFLICT", "attempt checkout path already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_git(["-C", str(repository_worktree), "worktree", "add", "--detach", str(destination), commit])


def remove_detached_worktree(repository_worktree: Path, destination: Path) -> None:
    if destination.exists():
        run_git(["-C", str(repository_worktree), "worktree", "remove", "--force", str(destination)], check=False)
