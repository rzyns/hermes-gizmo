import importlib.util
import json
from pathlib import Path

import pytest
import yaml


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
        """Nested dashboard-plugin copies must not contain tracked dist/ directories;
        assets are produced at the canonical root layout.
        """
        for plugin_name in ("tool-slimmer", "gizmo"):
            nested_dist = REPO_ROOT / "dashboard-plugin" / plugin_name / "dashboard" / "dist"
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

    def test_canonical_gizmo_dashboard_plugin_alias_exists(self):
        """The source tree should expose a canonical Gizmo dashboard plugin alias."""
        plugin_root = REPO_ROOT / "dashboard-plugin" / "gizmo"
        assert (plugin_root / "__init__.py").exists()
        assert (plugin_root / "plugin.yaml").exists()
        assert (plugin_root / "dashboard" / "manifest.json").exists()
        assert (plugin_root / "dashboard" / "plugin_api.py").exists()

    def test_canonical_gizmo_dashboard_manifest_is_distinct_alias(self):
        legacy = json.loads((REPO_ROOT / "dashboard-plugin" / "tool-slimmer" / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
        canonical = json.loads((REPO_ROOT / "dashboard-plugin" / "gizmo" / "dashboard" / "manifest.json").read_text(encoding="utf-8"))

        assert legacy["name"] == "tool-slimmer"
        assert legacy["tab"]["path"] == "/tool-slimmer"
        assert canonical["name"] == "gizmo"
        assert canonical["tab"]["path"] == "/gizmo"
        assert canonical["label"] == legacy["label"] == "Gizmo"
        assert canonical["entry"] == legacy["entry"] == "dist/index.js"
        assert canonical["css"] == legacy["css"] == "dist/style.css"
        assert canonical["api"] == legacy["api"] == "plugin_api.py"

    def test_canonical_gizmo_plugin_yaml_preserves_legacy_tool_surface(self):
        legacy = yaml.safe_load((REPO_ROOT / "dashboard-plugin" / "tool-slimmer" / "plugin.yaml").read_text(encoding="utf-8"))
        canonical = yaml.safe_load((REPO_ROOT / "dashboard-plugin" / "gizmo" / "plugin.yaml").read_text(encoding="utf-8"))

        assert legacy["name"] == "tool-slimmer"
        assert canonical["name"] == "gizmo"
        for field in ("provides_tools", "provides_hooks", "optional_hooks", "provides_commands", "provides_cli"):
            assert set(canonical.get(field, [])) == set(legacy.get(field, []))

    def test_canonical_gizmo_dashboard_api_proxies_legacy_router(self, monkeypatch):
        import sys
        import types
        from types import SimpleNamespace

        class FakeAPIRouter:
            def __init__(self):
                self.routes = []

            def get(self, path, **_kwargs):
                def decorator(func):
                    self.routes.append(SimpleNamespace(path=path, endpoint=func))
                    return func

                return decorator

            def post(self, path, **_kwargs):
                def decorator(func):
                    self.routes.append(SimpleNamespace(path=path, endpoint=func))
                    return func

                return decorator

        class FakeHTTPException(Exception):
            def __init__(self, status_code, detail=None):
                self.status_code = status_code
                self.detail = detail
                super().__init__(detail)

        fake_fastapi = types.ModuleType("fastapi")
        fake_fastapi.APIRouter = FakeAPIRouter
        fake_fastapi.Body = lambda default=None, **_kwargs: default
        fake_fastapi.HTTPException = FakeHTTPException
        fake_fastapi.Query = lambda default=None, **_kwargs: default
        monkeypatch.setitem(sys.modules, "fastapi", fake_fastapi)

        legacy_path = REPO_ROOT / "dashboard-plugin" / "tool-slimmer" / "dashboard" / "plugin_api.py"
        canonical_path = REPO_ROOT / "dashboard-plugin" / "gizmo" / "dashboard" / "plugin_api.py"

        legacy_spec = importlib.util.spec_from_file_location("legacy_tool_slimmer_plugin_api", legacy_path)
        canonical_spec = importlib.util.spec_from_file_location("canonical_gizmo_plugin_api", canonical_path)
        assert legacy_spec and legacy_spec.loader
        assert canonical_spec and canonical_spec.loader
        legacy_module = importlib.util.module_from_spec(legacy_spec)
        canonical_module = importlib.util.module_from_spec(canonical_spec)
        legacy_spec.loader.exec_module(legacy_module)
        canonical_spec.loader.exec_module(canonical_module)

        legacy_routes = sorted(route.path for route in legacy_module.router.routes)
        canonical_routes = sorted(route.path for route in canonical_module.router.routes)
        assert canonical_routes == legacy_routes

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

    def test_pyproject_wheel_includes_dashboard_and_plugin(self):
        """Wheel must explicitly include dashboard and dashboard-plugin so
        built wheels contain the required assets (HGZ-29a regression).
        """
        pyproject = REPO_ROOT / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        # The [tool.hatch.build.targets.wheel] section must list both directories
        wheel_section = text.split("[tool.hatch.build.targets.wheel]")[-1]
        assert '"/dashboard"' in wheel_section
        assert '"/dashboard-plugin"' in wheel_section
