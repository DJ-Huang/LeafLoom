"""Validate native desktop builds and assemble an explicitly unpublished release.

Uses the runner's gh CLI and GITHUB_REPOSITORY/GH_TOKEN. Never creates tags,
changes versions, or publishes a release. No application dependencies required.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
STABLE = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
WARNING = (
    "## Signing status\n\n"
    "Windows is unsigned. macOS uses ad-hoc signing and is not Apple-notarized. "
    "SmartScreen/Gatekeeper may warn or block installation. Passing CI does not "
    "certify installation on another machine.\n\n"
    "Both native builds passed the checks recorded in the linked workflow run. "
    "Verify the installers and SHA256SUMS.txt before manually publishing this draft.\n"
)


def application_version(root=ROOT, tag=""):
    versions = {}
    for directory in ("web", "desktop"):
        for name in ("package.json", "package-lock.json"):
            filename = f"{directory}/{name}"
            data = json.loads((root / filename).read_text(encoding="utf-8"))
            versions[filename] = data["version"]
            if name == "package-lock.json":
                versions[filename + " packages[root]"] = data["packages"][""]["version"]
    versions["pyproject.toml"] = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    versions["uv.lock"] = next(p["version"] for p in lock["package"] if p["name"] == "vault-rag")
    module = ast.parse((root / "vault_rag/__init__.py").read_text(encoding="utf-8"))
    versions["vault_rag/__init__.py"] = next(
        ast.literal_eval(node.value) for node in module.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    version = versions["desktop/package.json"]
    if not STABLE.fullmatch("v" + version):
        raise ValueError("Expected a stable X.Y.Z application version")
    if tag and (not STABLE.fullmatch(tag) or tag != "v" + version):
        raise ValueError(f"Tag {tag!r} must equal v{version}")
    if any(value != version for value in versions.values()):
        raise ValueError(f"Application versions disagree: {versions}")
    return version


def gh_json(*arguments, body=None):
    command = ["gh", "api", *arguments]
    if body is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(body) if body is not None else None,
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def find_release(repository, tag):
    # List (including drafts with authentication), rather than treating any API
    # error as a missing release. Permission/network failures must stop delivery.
    pages = gh_json(f"repos/{repository}/releases?per_page=100", "--paginate", "--slurp")
    return next((r for page in pages for r in page if r["tag_name"] == tag), None)


def require_draft(release):
    if release is not None and not release["draft"]:
        raise ValueError("Release is already public; refusing to replace its assets")


def artifacts(directory, version):
    names = [f"LeafLoom-{version}-windows-x64-setup.exe", f"LeafLoom-{version}-macos-arm64.dmg"]
    files = [directory / name for name in names]
    if any(not file.is_file() or file.is_symlink() or file.stat().st_size == 0 for file in files):
        raise ValueError("Both nonempty native installers are required")
    actual = {file.name for file in directory.iterdir() if file.suffix in (".exe", ".dmg")}
    if actual != set(names):
        raise ValueError("Unexpected installer names or versions")
    return files


def checksum(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_assets(repository, release_id, files):
    pages = gh_json(f"repos/{repository}/releases/{release_id}/assets?per_page=100", "--paginate", "--slurp")
    remote = {asset["name"]: asset for page in pages for asset in page}
    for file in files:
        asset = remote.get(file.name)
        if not asset or asset["size"] != file.stat().st_size:
            raise ValueError(f"Missing or wrong-size remote asset: {file.name}")
        expected = checksum(file)
        digest = asset.get("digest")
        if digest:
            if digest != "sha256:" + expected:
                raise ValueError(f"Remote SHA-256 mismatch: {file.name}")
        else:
            # Older API responses may lack a digest. Download the authenticated
            # draft asset and verify its bytes instead of accepting size alone.
            with tempfile.TemporaryFile() as stream:
                subprocess.run(["gh", "api", f"repos/{repository}/releases/assets/{asset['id']}",
                                "-H", "Accept: application/octet-stream"], stdout=stream, check=True)
                stream.seek(0)
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError(f"Downloaded SHA-256 mismatch: {file.name}")


def create_draft(repository, tag, directory):
    version = application_version(tag=tag)
    files = artifacts(directory, version)
    # Refuse a deleted/moved tag rather than letting the Releases API recreate
    # it at the default branch or attach binaries built from another commit.
    commit = gh_json(f"repos/{repository}/commits/{tag}")
    if commit["sha"] != os.environ["GITHUB_SHA"]:
        raise ValueError("Release tag no longer points to the workflow commit")
    release = find_release(repository, tag)
    require_draft(release)
    manifest = directory / "SHA256SUMS.txt"
    manifest.write_text("".join(f"{checksum(file)}  {file.name}\n" for file in files), encoding="utf-8", newline="\n")
    files.append(manifest)
    if release is None:
        notes = gh_json(f"repos/{repository}/releases/generate-notes", body={"tag_name": tag})["body"]
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        release = gh_json(f"repos/{repository}/releases", body={
            "tag_name": tag, "name": f"LeafLoom {version}", "draft": True,
            "prerelease": False, "body": WARNING + f"\n[Build logs and reports]({run_url})\n\n" + notes,
        })
    # Preserve user-edited notes on reruns. Recheck public status immediately
    # before replacing files; a failed upload always leaves a draft to inspect.
    for file in files:
        require_draft(gh_json(f"repos/{repository}/releases/{release['id']}"))
        subprocess.run(["gh", "release", "upload", tag, str(file), "--repo", repository, "--clobber"], check=True)
    verify_assets(repository, release["id"], files)
    require_draft(gh_json(f"repos/{repository}/releases/{release['id']}"))
    url = release["html_url"]
    print(f"Draft ready (not published): {url}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"## Desktop release draft\n\n[Review and manually publish]({url})\n\n")
            stream.write("Both installers and SHA256SUMS.txt verified by size and SHA-256.\n\n" + WARNING)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "draft"))
    parser.add_argument("--artifacts", type=Path, default=ROOT / "dist/release")
    args = parser.parse_args()
    tag = os.environ.get("RELEASE_TAG", "")
    version = application_version(tag=tag)
    if tag:
        require_draft(find_release(os.environ["GITHUB_REPOSITORY"], tag))
    if args.command == "draft":
        if not tag:
            parser.error("draft requires RELEASE_TAG")
        create_draft(os.environ["GITHUB_REPOSITORY"], tag, args.artifacts)
    else:
        print(f"Application versions match: {version}")


if __name__ == "__main__":
    main()
