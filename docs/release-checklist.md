# Release checklist

Publication is a separate maintainer-approved action. Do not push tags, publish packages, create releases, or announce a release until the target commit and action are explicitly approved.


## Semantic versioning policy

Hermes Gizmo follows [Semantic Versioning 2.0.0](https://semver.org/) using `MAJOR.MINOR.PATCH` versions and optional SemVer prerelease/build metadata.

While the project is still in the `0.y.z` community-preview line, the public API is not declared stable. Use:

- `PATCH` by incrementing the third number, for backward-compatible fixes and documentation-only corrections.
- `MINOR` by incrementing the second number and resetting patch to `0`, for new features, compatibility aliases, public CLI/plugin/dashboard surface additions, or behavior changes that users should notice.
- prereleases such as `0.8.0-alpha.1` or `1.0.0-rc.1` when testing a candidate before a final release.

Do not reuse an existing tag. If a version tag exists on any local or remote lineage, choose the next SemVer version instead.

After `1.0.0`, apply normal SemVer strictly: breaking public API/CLI/config/data-contract changes require `MAJOR`, backward-compatible features require `MINOR`, and backward-compatible fixes require `PATCH`.

1. Reconcile remotes/tags and choose the release version.
2. Update all version-bearing files consistently:
   - `pyproject.toml`
   - `src/hermes_tool_slimmer/__init__.py`
   - root and dashboard plugin `plugin.yaml` files
   - dashboard `manifest.json` files
3. Update `CHANGELOG.md` with user-facing changes and migration notes.
4. Run package validation:

   ```bash
   ruff check .
   mypy src tests
   python -m compileall -q src tests dashboard-plugin/tool-slimmer dashboard-plugin/gizmo
   pytest -q
   python -m build
   scripts/check-wheel-assets.sh
   ```

5. Smoke-test a temp install without `PYTHONPATH`:

   ```bash
   python -m venv /tmp/hermes-gizmo-smoke
   /tmp/hermes-gizmo-smoke/bin/python -m pip install -U pip
   /tmp/hermes-gizmo-smoke/bin/python -m pip install dist/*.whl
   /tmp/hermes-gizmo-smoke/bin/hermes-gizmo --help
   ```

6. Validate the Hermes core patch artifact against a clean Hermes checkout if the patch changed.
7. Run a pre-publication scan for secrets, private paths, stale URLs, and unexpected binaries.
8. Confirm `README.md`, `docs/`, `examples/`, `SUPPORT.md`, and `SECURITY.md` match the release behavior.
9. Push only the intended branch/tag refs. Do not use `git push --all` or `git push --mirror` from a repo containing backup/RC/notes refs.
