# Contributing

Author: Neriton Dias (@neritondias). MIT license.

Open an issue with the problem, version and sanitized reproduction steps. Keep changes in the plugin: do not ship Hermes core patches or personal credentials/configuration.

Contributions are welcome through fork-based pull requests. **Only Neriton Dias (@NeritonDias), the repository owner, merges pull requests into main.** CODEOWNERS requests his review; repository rules restrict main updates to the owner. An approval from another contributor does not authorize a merge.

## Tests

Use the documented Hermes checkout and its Python environment:

```bash
HERMES_SOURCE=/path/to/hermes-agent python scripts/test.py
hermes plugins doctor . --ci
hermes plugins compat .
```

The runner creates an isolated temporary profile and removes RYZEAPI_ variables. Tests use mocked responses; they do not send WhatsApp messages or create real instances. Skill-loader tests use native Hermes components.

Separate visual checks live in `tests/test_ui_tasks.py` and `tests/test_ui_groups.py`. They need Playwright/Chromium and `RYZE_UI_HARNESS` pointing to `tests/ui_harness.jsx` compiled with React/ReactDOM through esbuild. `HERMES_SOURCE` identifies the checkout. The harness intercepts networking and uses synthetic fixtures; these checks do not prove real authentication or provider operations.

## Change guidelines

- Keep settings/data outside code; do not add the author's phone, instance or domain as defaults.
- Test firewall, chat/instance correlation, idempotency and failures before adding formats.
- Never convert a LID to a phone number by stripping its suffix.
- Keep webhook fallback; never automatically repeat an uncertain mutation.
- Keep plugin/dashboard versions, skill metadata, documentation and tests consistent.
- The ryzeapi skill guides conversation/API use; ryzeapi-painel guides the dashboard. Public documentation does not mean a corresponding tool is installed.
- Test both skills' installation, managed updates and preservation of user edits.
- Maintain the English README and installation guide together with their PT-BR counterparts.
- Do not attach databases, raw event dumps or private logs to pull requests.

Scan the directory and Git history for secrets before publishing. A clean scanner result is not an independent security audit.
