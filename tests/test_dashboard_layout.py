import json
from pathlib import Path

import pytest


# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
DIST_DIR = DASHBOARD_DIR / "dist"
MANIFEST = DASHBOARD_DIR / "manifest.json"


class TestDashboardAssetLayout:
    """Regression: the dashboard manifest references assets that must exist at the
    canonical repo root dashboard/dist path, not only under a nested dashboard-plugin copy.
    """

    def test_manifest_exists_and_valid(self):
        assert MANIFEST.exists(), "dashboard/manifest.json must exist"
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert data.get("name") == "tool-slimmer"
        assert "entry" in data
        assert "css" in data

    def test_canonical_js_asset_exists(self):
        assert (DIST_DIR / "index.js").exists(), (
            "dashboard/dist/index.js must exist at the canonical repo root layout"
        )

    def test_canonical_css_asset_exists(self):
        assert (DIST_DIR / "style.css").exists(), (
            "dashboard/dist/style.css must exist at the canonical repo root layout"
        )

    def test_manifest_entry_resolves_to_existing_file(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        entry = data.get("entry", "dist/index.js")
        assert (DASHBOARD_DIR / entry).exists(), (
            f"manifest entry '{entry}' must resolve to an existing file under dashboard/"
        )

    def test_manifest_css_resolves_to_existing_file(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        css = data.get("css", "dist/style.css")
        assert (DASHBOARD_DIR / css).exists(), (
            f"manifest css '{css}' must resolve to an existing file under dashboard/"
        )

    def test_manifest_entry_matches_expected_relative_path(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert data.get("entry") == "dist/index.js"

    def test_manifest_css_matches_expected_relative_path(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert data.get("css") == "dist/style.css"

    def test_no_nested_duplicate_dist_tracked(self):
        """The nested dashboard-plugin copy must not contain a dist/ directory
        in the git-tracked tree; assets are produced at the canonical root layout.
        """
        nested_dist = REPO_ROOT / "dashboard-plugin" / "tool-slimmer" / "dashboard" / "dist"
        # If the directory still exists on disk but is untracked, that's acceptable
        # during development, but it should not be tracked by git.
        if nested_dist.exists():
            result = pytest.importorskip("subprocess").run(
                ["git", "ls-files", str(nested_dist)],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
            tracked = result.stdout.strip()
            assert tracked == "", f"Nested dist should not be git-tracked, but found: {tracked}"

    def test_installer_script_references_canonical_dist(self):
        installer = REPO_ROOT / "scripts" / "install-hermes-tool-slimmer.sh"
        script = installer.read_text(encoding="utf-8")
        assert 'DASHBOARD_SRC="$ROOT_DIR/dashboard"' in script
        assert '"$DASHBOARD_SRC/dist/index.js"' in script
        assert '"$DASHBOARD_SRC/dist/style.css"' in script

    def test_pyproject_artifacts_list_canonical(self):
        pyproject = REPO_ROOT / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        assert '"/dashboard/dist/index.js"' in text
        assert '"/dashboard/dist/style.css"' in text
