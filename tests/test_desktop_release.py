"""Release regressions use disposable installers and a mocked GitHub boundary."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import desktop_release as release


class DesktopReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("web", "desktop", "vault_rag"):
            (self.root / directory).mkdir()
        for directory in ("web", "desktop"):
            (self.root / directory / "package.json").write_text('{"version":"1.2.3"}')
            (self.root / directory / "package-lock.json").write_text(
                '{"version":"1.2.3","packages":{"":{"version":"1.2.3"}}}')
        (self.root / "pyproject.toml").write_text('[project]\nversion="1.2.3"\n')
        (self.root / "uv.lock").write_text('[[package]]\nname="vault-rag"\nversion="1.2.3"\n')
        (self.root / "vault_rag/__init__.py").write_text('__version__="1.2.3"\n')
        self.files = []
        for name in ("LeafLoom-1.2.3-windows-x64-setup.exe", "LeafLoom-1.2.3-macos-arm64.dmg"):
            file = self.root / name
            file.write_bytes(b"fictional installer " + name.encode())
            self.files.append(file)

    def test_versions_and_stable_tag(self):
        self.assertEqual(release.application_version(self.root, "v1.2.3"), "1.2.3")
        for tag in ("v1.2.4", "1.2.3", "v1.2.3-rc.1", "v01.2.3"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.application_version(self.root, tag)

    def test_each_application_version_must_agree(self):
        for filename in ("web/package.json", "web/package-lock.json", "desktop/package.json",
                         "desktop/package-lock.json", "pyproject.toml", "uv.lock", "vault_rag/__init__.py"):
            file = self.root / filename
            original = file.read_text()
            with self.subTest(filename=filename):
                file.write_text(original.replace("1.2.3", "1.2.4", 1))
                with self.assertRaises(ValueError):
                    release.application_version(self.root, "v1.2.3")
                file.write_text(original)

    def test_npm_root_lock_version_must_agree(self):
        file = self.root / "web/package-lock.json"
        data = json.loads(file.read_text())
        data["packages"][""]["version"] = "1.2.4"
        file.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            release.application_version(self.root)

    def test_missing_empty_and_wrong_version_installers(self):
        self.assertEqual(release.artifacts(self.root, "1.2.3"), self.files)
        self.files[1].unlink()
        with self.assertRaises(ValueError):
            release.artifacts(self.root, "1.2.3")
        self.files[1].touch()
        with self.assertRaises(ValueError):
            release.artifacts(self.root, "1.2.3")
        self.files[1].write_bytes(b"installer")
        (self.root / "LeafLoom-1.2.2-macos-arm64.dmg").write_bytes(b"stale")
        with self.assertRaises(ValueError):
            release.artifacts(self.root, "1.2.3")

    def test_github_errors_do_not_become_missing_release(self):
        with patch.object(release, "gh_json", side_effect=subprocess.CalledProcessError(1, "gh")):
            with self.assertRaises(subprocess.CalledProcessError):
                release.find_release("example/repo", "v1.2.3")

    def test_find_draft_on_later_page(self):
        draft = {"tag_name": "v1.2.3", "draft": True}
        with patch.object(release, "gh_json", return_value=[[{"tag_name": "v1.2.2"}], [draft]]):
            self.assertEqual(release.find_release("example/repo", "v1.2.3"), draft)

    def draft_fixture(self, existing=None, before_upload=None):
        draft = {"id": 123, "draft": True, "html_url": "https://github.com/example/repo/releases/123"}
        calls = []

        def api(endpoint, *args, body=None):
            calls.append((endpoint, body))
            if "/commits/" in endpoint:
                return {"sha": "fixture-commit"}
            if endpoint.endswith("generate-notes"):
                return {"body": "Generated notes"}
            if body is not None:
                return draft
            return before_upload or draft

        # Capture the function before patching to avoid recursive fixture calls.
        original = release.application_version
        version = lambda *args, **kwargs: original(self.root, kwargs.get("tag", ""))
        with patch.object(release, "application_version", side_effect=version), \
             patch.object(release, "find_release", return_value=existing), \
             patch.object(release, "gh_json", side_effect=api), \
             patch.object(release.subprocess, "run") as upload, \
             patch.object(release, "verify_assets") as verify, \
             patch.dict(os.environ, {"GITHUB_RUN_ID": "456", "GITHUB_SHA": "fixture-commit",
                                     "GITHUB_STEP_SUMMARY": str(self.root / "summary.md")}):
            release.create_draft("example/repo", "v1.2.3", self.root)
        return calls, upload, verify

    def test_create_unpublished_draft_with_both_installers_and_manifest(self):
        calls, upload, verify = self.draft_fixture()
        created = [body for _, body in calls if body and "draft" in body][0]
        self.assertIs(created["draft"], True)
        self.assertIs(created["prerelease"], False)
        self.assertIn("unsigned", created["body"])
        self.assertIn("Generated notes", created["body"])
        self.assertIn("actions/runs/456", created["body"])
        self.assertEqual(upload.call_count, 3)
        for file in self.files:
            self.assertTrue(any(str(file) in call.args[0] and "--clobber" in call.args[0] for call in upload.call_args_list))
        manifest = self.root / "SHA256SUMS.txt"
        self.assertEqual(manifest.read_text(), "".join(
            f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n" for file in self.files))
        verify.assert_called_once()

    def test_rerun_preserves_draft_notes(self):
        calls, upload, _ = self.draft_fixture(existing={"id": 123, "draft": True,
            "body": "User edited notes", "html_url": "https://github.com/example/repo/releases/123"})
        self.assertFalse(any(body is not None for _, body in calls))
        self.assertEqual(upload.call_count, 3)

    def test_public_release_blocks_all_writes(self):
        with patch.object(release, "application_version", return_value="1.2.3"), \
             patch.object(release, "find_release", return_value={"draft": False}), \
             patch.object(release, "gh_json", return_value={"sha": "fixture-commit"}) as api, \
             patch.dict(os.environ, {"GITHUB_SHA": "fixture-commit"}), \
             patch.object(release.subprocess, "run") as upload:
            with self.assertRaises(ValueError):
                release.create_draft("example/repo", "v1.2.3", self.root)
            self.assertEqual(api.call_count, 1)  # Read the tag; no API writes.
            upload.assert_not_called()

    def test_deleted_or_moved_tag_blocks_release_writes(self):
        with patch.object(release, "application_version", return_value="1.2.3"), \
             patch.object(release, "gh_json", return_value={"sha": "different-commit"}) as api, \
             patch.dict(os.environ, {"GITHUB_SHA": "fixture-commit"}), \
             patch.object(release.subprocess, "run") as upload:
            with self.assertRaises(ValueError):
                release.create_draft("example/repo", "v1.2.3", self.root)
            self.assertEqual(api.call_count, 1)
            upload.assert_not_called()

    def test_publication_during_build_blocks_upload(self):
        with self.assertRaises(ValueError):
            self.draft_fixture(existing={"id": 123, "draft": True}, before_upload={"draft": False})

    def test_remote_size_digest_and_missing_assets(self):
        assets = [{"name": file.name, "id": i, "size": file.stat().st_size,
                   "digest": "sha256:" + release.checksum(file)} for i, file in enumerate(self.files)]
        with patch.object(release, "gh_json", return_value=[assets]):
            release.verify_assets("example/repo", 123, self.files)
            assets[0]["size"] += 1
            with self.assertRaises(ValueError):
                release.verify_assets("example/repo", 123, self.files)
            assets[0]["size"] -= 1
            assets[0]["digest"] = "sha256:" + "0" * 64
            with self.assertRaises(ValueError):
                release.verify_assets("example/repo", 123, self.files)
            assets.clear()
            with self.assertRaises(ValueError):
                release.verify_assets("example/repo", 123, self.files)

    def test_missing_api_digest_downloads_and_hashes_draft_asset(self):
        file = self.files[0]
        asset = {"name": file.name, "id": 1, "size": file.stat().st_size}
        def download(*args, **kwargs):
            kwargs["stdout"].write(file.read_bytes())
        with patch.object(release, "gh_json", return_value=[[asset]]), \
             patch.object(release.subprocess, "run", side_effect=download):
            release.verify_assets("example/repo", 123, [file])

    @unittest.skipUnless(shutil.which("node"), "Node required for builder configuration")
    def test_unsigned_mac_configuration_and_signed_defaults(self):
        for unsigned in ("0", "1"):
            env = dict(os.environ, LEAFLOOM_UNSIGNED=unsigned, APPLE_ID="fixture@example.invalid")
            result = subprocess.check_output(["node", "-e",
                "console.log(JSON.stringify(require('./desktop/electron-builder.config.cjs').mac))"],
                cwd=release.ROOT, env=env, text=True)
            mac = json.loads(result)
            self.assertEqual(mac["hardenedRuntime"], unsigned == "0")
            self.assertEqual(mac["notarize"], unsigned == "0")
            self.assertEqual(mac.get("identity"), "-" if unsigned == "1" else None)


if __name__ == "__main__":
    unittest.main()
