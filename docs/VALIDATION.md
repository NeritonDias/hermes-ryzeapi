# Release validation

## Baseline: 0.14.0-beta.1

Date: September 15, 2026. Hermes commit `a982d2c882ce14aca6e98873b32d3dce8a496a27`; Linux ARM64 and Python 3.12.14.

- 217 automated tests passed in 24.001 seconds using an isolated profile without production credentials.
- Plugin Doctor passed: import, manifest and native registration; 14 tools.
- Plugin compat passed: no imports detected on the Hermes removal list.
- Both skills: installation, idempotence, managed update/backup, name conflict, local edits, extra references, symlink rejection and failed-update rollback covered.
- Native Hermes parser/linter, skills_list, skill_view, references and both slash commands passed.
- Synthetic browser tests: 23 task scenarios and 25 group scenarios passed, without page errors, on desktop/mobile viewports and with provider networking blocked.
- Gitleaks 8.30.1 found no secrets in the public directory or published Git history.
- Real native installation and update from GitHub in a clean profile passed. Both skills were installed/listed/readable through short and namespaced names, without separate skill installation or provider calls.
- [GitHub CI](https://github.com/NeritonDias/hermes-ryzeapi/actions/runs/35036229646) passed 217 tests on Linux x64.

The native Hermes scanner reported CAUTION for reviewed synthetic fixtures and test/CI commands. Findings included test tokens, intentionally invalid paths, loopback addresses and test execution/dependency installation. Tests were not removed to hide warnings. Review the current report before accepting installation.

## 1.0.0-beta.1 scope

This release changes documentation and version metadata, not the runtime implementation. It adds automated checks for version consistency, bilingual documentation and local links. Current automated results are published under [GitHub Actions](https://github.com/NeritonDias/hermes-ryzeapi/actions/workflows/test.yml).

The updated suite passed **221 tests in 23.703 seconds** on the Linux ARM64 baseline, in an isolated profile. Four new checks cover release metadata, language switches/provider documentation, local links/anchors and installation tutorial contracts.

The browser and real WhatsApp observations above belong to the previous validation baseline; they are not newly repeated end-to-end tests of this documentation release. See release notes for this release's rerun results.

## Conversation tests

The earlier skill refinement, with one skill plus a dashboard reference, was exercised in three real Hermes sessions. Historical traces and limitations are documented in [SKILL-VALIDATION.md](SKILL-VALIDATION.md) (Portuguese).

The dashboard then became a separate skill. Native installation/discovery checks verify its loading. Discovery/decision tests do not prove real execution of every endpoint.

## Not established by these checks

- Every operating system or future Hermes commit.
- Live Telegram/Discord transport or administrative permissions across all channels.
- Every message format rendering in every WhatsApp client.
- Final human confirmation of the renewed button/list reply cycle, media carousels, or all form/vote/event returns.
- An installed executable tool for every RyzeAPI operation.
- Full feature parity with the built-in Hermes WhatsApp channel.

Tests did not publish Status, perform payments or create real instances. This is not an official integration or an independently audited release.
