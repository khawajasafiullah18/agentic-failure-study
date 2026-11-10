"""Move the repository and the dataset release to a project namespace.

Run this only when the destination exists. It is dry-run by default: it prints
what it would do, checks that it can do it, and changes nothing. Add --apply to
execute.

    # inspect first (safe, changes nothing)
    python tools/move_project.py --gh-org my-lab --hf-org my-lab

    # execute, then relink every artefact and prove no stale URL survived
    python tools/move_project.py --gh-org my-lab --hf-org my-lab --apply

What it does, in order:

    1. checks the token can administer the repository (a transfer needs admin,
       not write) and that the destination org exists;
    2. transfers the GitHub repository, which carries issues, stars, Pages
       configuration and the Actions secrets that deploy the site;
    3. moves the Hugging Face dataset, which preserves the record identifiers;
    4. rewrites src/afs/identity.py's defaults to the new namespace;
    5. rebuilds the artefacts that embed a link (report, paper, deck, handover
       package, dataset card, CITATION.cff);
    6. runs tools/check_identity.py and fails loudly if a stale link survived.

Deliberately NOT automated: creating the destination organization. GitHub has no
API for creating a free organization, so that is a browser step, and it is also
where the name is chosen - a decision that ends up in a submitted report's URLs
and should be made by a person, not defaulted by a script.

Also NOT automated: granting access to anyone else. The move puts the project
under project ownership; who can then administer it is a separate, deliberate
decision.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afs import identity  # noqa: E402

IDENTITY_FILE = ROOT / "src" / "afs" / "identity.py"


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def gh_api(path: str, method: str = "GET", fields: dict | None = None) -> dict:
    cmd = ["gh", "api", "-X", method, path]
    for k, v in (fields or {}).items():
        cmd += ["-f", f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or out.stdout.strip())
    return json.loads(out.stdout) if out.stdout.strip() else {}


def check_github(org: str) -> list[str]:
    notes: list[str] = []
    repo = f"{identity.GH_OWNER}/{identity.GH_REPO}"
    try:
        r = gh_api(f"/repos/{repo}")
    except RuntimeError as e:
        return [f"cannot read {repo}: {e}"]

    if not (r.get("permissions") or {}).get("admin"):
        notes.append(
            f"token lacks admin on {repo} (has "
            f"{[k for k, v in (r.get('permissions') or {}).items() if v]}); "
            f"a transfer requires admin, so transfer it in Settings instead")

    try:
        o = gh_api(f"/orgs/{org}")
        notes.append(f"destination org exists: {o.get('login')} (plan {o.get('plan', {}).get('name')})")
    except RuntimeError:
        members = []
        try:
            members = [u["login"] for u in gh_api("/user/orgs")]
        except RuntimeError:
            pass
        notes.append(
            f"destination org '{org}' not found or token is not a member"
            + (f" (token belongs to orgs: {', '.join(members)})" if members else
               " (token belongs to no organization)")
            + " - create it at https://github.com/organizations/new first")

    warn = []
    if r.get("has_pages"):
        warn.append("repository has GitHub Pages; the old Pages URL will redirect "
                    "but the canonical URL becomes the org one, so citations move")
    if r.get("has_issues"):
        warn.append("issues transfer with the repository; their numbers are preserved")
    return notes + [f"note: {w}" for w in warn]


def check_hf(org: str, token: str | None) -> list[str]:
    notes: list[str] = []
    if not token:
        notes.append("no Hugging Face token found (set HF_TOKEN); the dataset move "
                     "cannot run, but the GitHub half still can")
        return notes
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        me = api.whoami()
        notes.append(f"Hugging Face identity: {me.get('name')}")
        try:
            api.get_organization_overview(org, token=token)
            notes.append(f"destination HF org exists: {org}")
        except Exception:
            notes.append(f"destination HF org '{org}' not found or token is not a "
                         f"member - create it at https://huggingface.co/organizations/new")

        # A fine-grained token can be scoped to the user only, in which case it
        # cannot write into an organization even after the user joins one. That
        # failure would surface halfway through the move, so it is checked here.
        auth = (me.get("auth") or {}).get("accessToken") or {}
        fg = auth.get("fineGrained") or {}
        if auth.get("role") == "fineGrained":
            scoped = [s.get("entity", {}).get("type")
                      for s in (fg.get("scoped") or [])]
            if "org" not in scoped:
                notes.append(
                    f"token '{auth.get('displayName')}' is fine-grained and scoped "
                    f"to {scoped or ['nothing']} - no organization scope, so it "
                    f"cannot write into {org}. Re-scope it to include the "
                    f"organization, or mint a classic write token, once the org "
                    f"exists")
            else:
                notes.append("token has organization scope")

        info = api.dataset_info(identity.HF_REPO_ID, token=token)
        notes.append(f"dataset reachable: {info.id} "
                     f"({len(info.siblings or [])} files)")
    except Exception as e:  # noqa: BLE001 - report, do not crash the dry run
        notes.append(f"Hugging Face check failed: {type(e).__name__}: {e}")
    return notes


# --------------------------------------------------------------------------- #
# moves
# --------------------------------------------------------------------------- #
def transfer_github(org: str) -> None:
    repo = f"{identity.GH_OWNER}/{identity.GH_REPO}"
    gh_api(f"/repos/{repo}/transfer", "POST", {"new_owner": org})
    print(f"  GitHub: {repo} -> {org}/{identity.GH_REPO}")


def move_hf(org: str, token: str) -> None:
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.move_repo(identity.HF_REPO_ID, f"{org}/{identity.HF_REPO}",
                  repo_type="dataset")
    print(f"  Hugging Face: {identity.HF_REPO_ID} -> {org}/{identity.HF_REPO}")


def fingerprint_hf(save_to: Path, repo_id: str | None = None) -> bool:
    """Capture the release contents so the move can be proven lossless."""
    script = ROOT / "tools" / "fingerprint_release.py"
    cmd = [sys.executable, str(script), "--save", str(save_to)]
    if repo_id:
        cmd += ["--repo", repo_id]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    ok = out.returncode == 0
    if ok:
        line = [l for l in out.stdout.splitlines() if "files," in l]
        print(f"  {'ok' if ok else 'FAILED'} {line[0] if line else ''}")
    else:
        print(f"  FAILED {(out.stderr or out.stdout).strip()[-400:]}")
    return ok


def verify_fingerprint(before: Path, repo_id: str) -> bool:
    script = ROOT / "tools" / "fingerprint_release.py"
    out = subprocess.run([sys.executable, str(script), "--verify", str(before),
                          "--repo", repo_id],
                         cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    print((out.stdout or out.stderr).strip())
    return out.returncode == 0


def rewrite_defaults(gh_org: str | None, hf_org: str | None) -> None:
    """Rewrite the defaults in identity.py, leaving the legacy constants alone.

    The legacy constants are the record of where the project used to live, which
    the dataset card and the handover page then reprint. They must survive the
    move for the provenance statement to be true.
    """
    text = IDENTITY_FILE.read_text(encoding="utf-8")
    original = text
    if gh_org:
        text = re.sub(r'(_env\("AFS_GH_OWNER", ")[^"]+("\))',
                      lambda m: m.group(1) + gh_org + m.group(2), text)
    if hf_org:
        text = re.sub(r'(_env\("AFS_HF_OWNER", ")[^"]+("\))',
                      lambda m: m.group(1) + hf_org + m.group(2), text)
    if text != original:
        IDENTITY_FILE.write_text(text, encoding="utf-8")
        print(f"  identity.py defaults updated ({len(original)} -> {len(text)} chars)")
    else:
        print("  identity.py unchanged (no default rewritten)")


def rebuild_and_check() -> int:
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    steps = [
        ([sys.executable, "-m", "afs.cli", "export"], "rebuild report/paper/deck"),
        ([sys.executable, "-m", "afs.cli", "hf"], "rebuild dataset card + CITATION.cff"),
        ([sys.executable, str(ROOT / "deploy" / "build_handover.py")], "rebuild handover package"),
        ([sys.executable, str(ROOT / "tools" / "check_identity.py")], "check for stale links"),
    ]
    rc = 0
    for cmd, label in steps:
        print(f"  {label} ...", end=" ", flush=True)
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                             env={**__import__("os").environ, **env})
        ok = out.returncode == 0
        print("ok" if ok else "FAILED")
        if not ok:
            rc = out.returncode
            print((out.stderr or out.stdout).strip()[-1500:])
    return rc


# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gh-org", help="GitHub organization to move the repository to")
    ap.add_argument("--hf-org", help="Hugging Face organization to move the dataset to")
    ap.add_argument("--apply", action="store_true", help="execute; default is a dry run")
    ap.add_argument("--skip-rebuild", action="store_true",
                    help="move only; leave artefacts to a later rebuild")
    args = ap.parse_args(argv)

    if not args.gh_org and not args.hf_org:
        print("nothing to do: pass --gh-org and/or --hf-org")
        return 2

    import os
    hf_token = os.environ.get("HF_TOKEN") or None

    print(f"current namespace: github={identity.GH_OWNER}/{identity.GH_REPO} "
          f"hf={identity.HF_REPO_ID}")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print("\npreflight")
    blockers: list[str] = []
    if args.gh_org:
        for n in check_github(args.gh_org):
            print(f"  {n}")
            if "not found" in n or "lacks admin" in n or n.startswith("cannot read"):
                blockers.append(n)
    if args.hf_org:
        for n in check_hf(args.hf_org, hf_token):
            print(f"  {n}")
            if "not found" in n or "no Hugging Face token" in n or "failed" in n:
                blockers.append(n)

    if blockers:
        print("\nblocked:")
        for b in blockers:
            print(f"  - {b}")
        if not args.apply:
            print("\ndry run: nothing changed")
        return 1

    if not args.apply:
        print("\nwould now:")
        if args.gh_org:
            print(f"  1. transfer {identity.GH_OWNER}/{identity.GH_REPO} to {args.gh_org}")
        if args.hf_org:
            print(f"  2. move {identity.HF_REPO_ID} to {args.hf_org}")
        print("  3. capture the release fingerprint (proves the move is lossless)")
        print("  4. rewrite identity.py defaults")
        print("  5. rebuild artefacts")
        print("  6. verify the release is byte-identical and no stale link survived")
        print("\ndry run: nothing changed. Re-run with --apply")
        return 0

    print("\nmoving")
    before = ROOT / "outputs" / "proof" / "release_fingerprint_before.json"
    if args.hf_org:
        print("  capturing the release contents before the move")
        before.parent.mkdir(parents=True, exist_ok=True)
        if not fingerprint_hf(before):
            print("  refusing to move without a fingerprint: the claim that the "
                  "move preserved the data would be unverifiable")
            return 1

    if args.gh_org:
        transfer_github(args.gh_org)
    if args.hf_org:
        move_hf(args.hf_org, hf_token)

    print("\nverifying the move preserved the release")
    preserved = True
    if args.hf_org:
        preserved = verify_fingerprint(
            before, f"{args.hf_org}/{identity.HF_REPO}")
        if preserved:
            after = before.with_name("release_fingerprint_after.json")
            fingerprint_hf(after, f"{args.hf_org}/{identity.HF_REPO}")

    print("\nrelinking")
    rewrite_defaults(args.gh_org, args.hf_org)

    if args.skip_rebuild:
        print("  skipped rebuild (--skip-rebuild); run afs.cli export/hf then "
              "tools/check_identity.py")
        return 0 if preserved else 1

    print("\nrebuilding")
    rc = rebuild_and_check()
    if not preserved:
        print("\nthe release fingerprint changed across the move - see above. "
              "Do not cite the new location until that is explained.")
        return rc or 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
