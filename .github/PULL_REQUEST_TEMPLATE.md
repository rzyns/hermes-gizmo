## Summary

<!-- What changed and why? -->

## Checklist

- [ ] Scope is focused; no unrelated formatter/dependency churn.
- [ ] Legacy `tool-slimmer` compatibility is preserved or migration impact is explained.
- [ ] Fail-open, disabled-tool, provider-gating, and privacy expectations are preserved.
- [ ] README/docs/examples are updated if user-visible behavior changed.
- [ ] Tests or regression coverage are included where practical.

## Validation

Paste the commands you ran and their results:

```bash
ruff check .
mypy src tests
python -m compileall -q src tests dashboard-plugin/tool-slimmer dashboard-plugin/gizmo
pytest -q
python -m build
scripts/check-wheel-assets.sh
```

## Security / privacy notes

<!-- Confirm no raw prompts, session IDs, credentials, private paths, or exploit details were introduced. -->
