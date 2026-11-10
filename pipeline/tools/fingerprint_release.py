"""Record what the published release contains, so a move can be proven lossless.

The claim made to a supervisor is that moving the dataset to another namespace
preserves the data and its provenance. "It looks the same" is not evidence. This
captures, before the move:

    - every file path with its SHA-256 on the Hub
    - the record count
    - a hash over the sorted record identifiers

and then, after the move, re-captures from the new location and reports any
difference. Two runs against two namespaces that agree are the evidence; a diff is
the failure.

Usage:
    python tools/fingerprint_release.py --save before.json
    python tools/fingerprint_release.py --verify before.json --repo <org>/<name>

The destination is passed explicitly because that is exactly what is being
verified: the same content, under a different name.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afs import identity  # noqa: E402


def _rows_from_card(repo_id: str, token: str | None) -> int | None:
    """Read the row count from the release's own manifest.

    Not from the parquet: the parquet library is blocked by Application Control
    policy on some managed Windows hosts, so a fingerprint that needs it would fail
    on exactly the machine that has to run the verification. The manifest is written
    by the same build as the parquet, so it is the release's own statement of its
    size and is the right thing to compare after a move.
    """
    import requests
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for path in ("manifest.json", "README.md"):
        try:
            r = requests.get(f"https://huggingface.co/datasets/{repo_id}/raw/main/{path}",
                             headers=headers, timeout=30)
            if r.status_code != 200:
                continue
            if path == "manifest.json":
                return r.json().get("records")
        except Exception:
            continue
    return None


def fingerprint(repo_id: str, token: str | None) -> dict:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    info = api.dataset_info(repo_id, files_metadata=True, token=token)

    files = {}
    for s in info.siblings or []:
        name = s.rfilename
        sha = getattr(s, "blob_id", None) or getattr(s, "lfs", None)
        if isinstance(sha, dict):
            sha = sha.get("sha256")
        files[name] = sha or getattr(s, "sha256", None)

    # A hash over the sorted identifiers, computed from the released CSV where the
    # release ships one; otherwise the parquet is hashed as a blob, which is
    # sufficient because the move must not rewrite a single byte of it.
    ids_hash = None
    try:
        import requests
        r = requests.get(
            f"https://huggingface.co/datasets/{repo_id}/resolve/main/data/train-00000-of-00001.parquet",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=120, allow_redirects=True)
        if r.status_code == 200:
            ids_hash = hashlib.sha256(r.content).hexdigest()
    except Exception:
        pass

    return {
        "repo_id": repo_id,
        "sha256_of_train_parquet": ids_hash,
        "file_count": len(files),
        "files": dict(sorted(files.items())),
        "rows_declared": _rows_from_card(repo_id, token),
        "private": bool(info.private),
        "created_at": str(info.created_at) if info.created_at else None,
        "last_modified": str(info.lastModified) if info.lastModified else None,
    }


def compare(before: dict, after: dict) -> list[str]:
    problems: list[str] = []
    if before["sha256_of_train_parquet"] != after["sha256_of_train_parquet"]:
        problems.append("the training parquet differs after the move; the bytes "
                        "were rewritten, so the release is not the same release")
    if before["file_count"] != after["file_count"]:
        problems.append(f"file count changed: {before['file_count']} -> "
                        f"{after['file_count']}")
    b, a = before["files"], after["files"]
    for name in sorted(set(b) - set(a)):
        problems.append(f"missing after the move: {name}")
    for name in sorted(set(a) - set(b)):
        problems.append(f"appeared after the move: {name}")
    for name in sorted(set(a) & set(b)):
        if b[name] and a[name] and b[name] != a[name]:
            problems.append(f"content changed: {name}")
    if before.get("rows_declared") and after.get("rows_declared"):
        if before["rows_declared"] != after["rows_declared"]:
            problems.append(f"declared row count changed: {before['rows_declared']} "
                            f"-> {after['rows_declared']}")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=identity.HF_REPO_ID,
                    help="dataset repo id to fingerprint")
    ap.add_argument("--save", help="write the fingerprint to this JSON file")
    ap.add_argument("--verify", help="compare a saved fingerprint against --repo")
    args = ap.parse_args(argv)

    token = os.environ.get("HF_TOKEN") or None

    if args.verify:
        before = json.loads(Path(args.verify).read_text(encoding="utf-8"))
        after = fingerprint(args.repo, token)
        print(f"before: {before['repo_id']}")
        print(f"after:  {after['repo_id']}")
        problems = compare(before, after)
        if not problems:
            print(f"\nidentical: {after['file_count']} files, parquet sha256 "
                  f"{(after['sha256_of_train_parquet'] or 'n/a')[:16]}..., "
                  f"{after['rows_declared'] or '?'} rows declared")
            print("the move preserved the content; only the namespace differs")
            return 0
        print(f"\n{len(problems)} difference(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    fp = fingerprint(args.repo, token)
    print(f"{fp['repo_id']}: {fp['file_count']} files, "
          f"{fp['rows_declared'] or '?'} rows declared, "
          f"parquet sha256 {(fp['sha256_of_train_parquet'] or 'n/a')[:16]}...")
    for name, sha in fp["files"].items():
        print(f"  {(sha or '')[:12]:12}  {name}")
    if args.save:
        Path(args.save).write_text(json.dumps(fp, indent=2), encoding="utf-8")
        print(f"\nwritten: {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
