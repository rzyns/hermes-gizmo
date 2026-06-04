# Security Policy

Hermes Gizmo changes which tool schemas are presented to the model. It does **not** execute tools, grant approvals, bypass Hermes permission checks, or change provider credentials.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Please report security issues privately by opening a GitHub security advisory or contacting the repository owner. Include:

- affected version or commit
- reproduction steps
- expected and actual behavior
- whether the issue can remove safety-critical tools, bypass fail-open behavior, or expose credentials

## Security expectations

- Selector errors must fail open to the original Hermes schema list.
- Disabled tools and disabled toolsets must never be reintroduced by this plugin.
- `dry_run` must not alter schemas.
- Provider-specific Tool Search features must be gated by provider capability, not model-name guesses alone.
