# Support

Hermes Gizmo is an alpha/community-preview Hermes Agent plugin. Support is best-effort.

## Where to ask

- **Install bugs, dashboard issues, ranking misses, and docs problems:** open an issue at https://github.com/rzyns/hermes-gizmo/issues.
- **Security-sensitive reports:** follow `SECURITY.md`; do not post exploit details or secrets in public issues.
- **General Hermes Agent questions unrelated to Gizmo:** use the appropriate Hermes Agent community/support channel instead of this repo.

## What to include

For bugs, include:

- Hermes Agent version
- Hermes Gizmo version or commit SHA
- install method: dashboard git install, script installer, editable checkout, or package install
- relevant sanitized config (`tool_slimmer` section, with secrets removed)
- output from `hermes tool-slimmer doctor` or `hermes gizmo doctor` when available
- expected behavior and actual behavior

## Boundaries

Hermes Gizmo does not promise billable token savings, support every Hermes fork, bypass Hermes permissions, or provide emergency/production SRE support. The plugin should preserve Hermes safety controls and fail open on selector errors.
