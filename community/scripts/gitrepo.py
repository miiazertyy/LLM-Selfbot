"""gitrepo.py - the community's data branch, changed and pushed by the workflows.

The profiles live on a branch of their own in the app's repo (community_rules.DATA_BRANCH), checked out beside the
code. Commits are made as github-actions[bot] and only ever pushed to that branch: never to the app's own. A push that
loses a race (another run pushed first) is rebased and tried again, so two workflows never undo each other.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import community_rules as rules

BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
# The app's own branches: whatever happens, nothing here is pushed to them.
NEVER = frozenset({"main", "master"})


class Repo:
    def __init__(self, root, branch: str = rules.DATA_BRANCH):
        if branch in NEVER:
            raise ValueError(f"not a branch the community writes to: {branch}")
        self.root = Path(root)
        self.branch = branch

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"outside the repo: {rel}")
        return p

    def read(self, rel: str) -> bytes | None:
        p = self.path(rel)
        return p.read_bytes() if p.is_file() else None

    def write(self, rel: str, data: bytes) -> None:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def remove(self, rel: str) -> None:
        p = self.path(rel)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    def git(self, *args, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.root), "-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}",
                               *args], capture_output=True, text=True, check=check)

    def changed(self) -> bool:
        return bool(self.git("status", "--porcelain").stdout.strip())

    def commit_and_push(self, message: str, tries: int = 4) -> bool:
        """Everything changed, committed and pushed to the data branch. False when there was nothing to commit."""
        self.git("add", "-A")
        if not self.git("diff", "--cached", "--quiet", check=False).returncode:
            return False
        self.git("commit", "-q", "-m", message)
        for attempt in range(tries):
            if not self.git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", check=False).returncode:
                return True
            self.git("pull", "-q", "--rebase", "origin", self.branch, check=False)
        raise RuntimeError("The repo couldn't be pushed to.")

    def restore(self, rel: str) -> bool:
        """A path brought back as it was just before the commit that removed it. False when it never existed."""
        log = self.git("log", "--diff-filter=D", "-n", "1", "--format=%H", "--", rel, check=False).stdout.strip()
        if not log:
            return False
        return not self.git("checkout", f"{log}^", "--", rel, check=False).returncode


def _exists(checkout: Path, branch: str, remote: str) -> bool:
    has = subprocess.run(["git", "-C", str(checkout), "ls-remote", "--exit-code", "--heads", remote, branch],
                         capture_output=True, text=True)
    if has.returncode not in (0, 2):
        raise RuntimeError("The repo couldn't be reached.")
    return has.returncode == 0


def _tree(checkout: Path, folder: Path) -> str:
    """A folder written into the checkout's git objects as a tree, files and all. Returns the tree's id."""
    def git(*args, data=None):
        return subprocess.run(["git", "-C", str(checkout), *args], input=data, capture_output=True,
                              check=True).stdout.decode().strip()
    lines = []
    for p in sorted(folder.iterdir()):
        if p.is_dir():
            lines.append(f"040000 tree {_tree(checkout, p)}\t{p.name}")
        elif p.is_file():
            lines.append(f"100644 blob {git('hash-object', '-w', '--', str(p))}\t{p.name}")
    return git("mktree", data=("\n".join(lines) + "\n").encode())


def seed_branch(checkout: Path, seed: Path, branch: str = rules.DATA_BRANCH, remote: str = "origin") -> bool:
    """The data branch made from the files in `seed` when the remote hasn't got it: an orphan commit (no history shared
    with the app's code), built inside the app's checkout without touching its files, and pushed with the checkout's
    own sign-in. True when it was made, False when it was there already or another run made it first. (Two runs in
    the same second make the very same commit, so both may say they made it: the branch is the same either way.)"""
    if branch in NEVER:
        raise ValueError(f"not a branch the community writes to: {branch}")
    checkout = Path(checkout)
    if _exists(checkout, branch, remote):
        return False
    tree = _tree(checkout, Path(seed))
    env = {**os.environ, "GIT_AUTHOR_NAME": BOT[0], "GIT_AUTHOR_EMAIL": BOT[1], "GIT_COMMITTER_NAME": BOT[0],
           "GIT_COMMITTER_EMAIL": BOT[1]}
    commit = subprocess.run(["git", "-C", str(checkout), "commit-tree", tree, "-m", "Start the community profiles"],
                            capture_output=True, text=True, check=True, env=env).stdout.strip()
    pushed = subprocess.run(["git", "-C", str(checkout), "push", "-q", remote, f"{commit}:refs/heads/{branch}"],
                            capture_output=True, text=True)
    if pushed.returncode:
        if _exists(checkout, branch, remote):
            return False
        raise RuntimeError(f"The {branch} branch couldn't be made: {pushed.stderr.strip()[-300:]}")
    return True
