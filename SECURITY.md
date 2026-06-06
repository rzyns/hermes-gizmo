# Security Policy

Hermes Gizmo changes which tool schemas are presented to the model. It does **not** execute tools, grant approvals, bypass Hermes permission checks, or change provider credentials.

## Supported versions

Hermes Gizmo is currently an alpha/community-preview project. Security fixes are handled on a best-effort basis for the latest released version and current `main` branch. Older release lines are not guaranteed to receive backports unless a maintainer explicitly announces support for that line.

| Version | Supported |
|---|---|
| Latest release / current `main` | Best effort |
| Older releases | Not guaranteed |

## Reporting a vulnerability

Please report security issues privately by opening a GitHub Security Advisory for the repository, or by contacting the repository maintainer through a private channel. Do **not** put exploit details, private logs, credentials, or reproduction payloads in a public issue.

Please include:

- affected version or commit
- Hermes Agent version and provider path, if relevant
- reproduction steps with secrets removed
- expected and actual behavior
- whether the issue can remove safety-critical tools, bypass fail-open behavior, expose credentials, or alter disabled-tool policy

## Security expectations

- Selector errors must fail open to the original Hermes schema list.
- Disabled tools and disabled toolsets must never be reintroduced by this plugin.
- `dry_run` must not alter schemas.
- Provider-specific Tool Search features must be gated by provider capability, not model-name guesses alone.
- Diagnostics must avoid raw prompts, environment secret values, and session IDs.
