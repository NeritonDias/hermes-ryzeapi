# Hermes × RyzeAPI

[![English](https://img.shields.io/badge/Language-English-196b62)](README.md) [![Português (Brasil)](https://img.shields.io/badge/Idioma-PT--BR-196b62)](README.pt-BR.md)
[![Release](https://img.shields.io/github/v/release/NeritonDias/hermes-ryzeapi?include_prereleases)](https://github.com/NeritonDias/hermes-ryzeapi/releases)
[![Tests](https://github.com/NeritonDias/hermes-ryzeapi/actions/workflows/test.yml/badge.svg)](https://github.com/NeritonDias/hermes-ryzeapi/actions/workflows/test.yml)

A community WhatsApp integration for **Hermes Agent** with a web dashboard, two bundled skills, persistent WebSocket connectivity and webhook fallback.

**Author: Neriton Dias** · [Instagram @neritondias](https://www.instagram.com/neritondias/) · [MIT license](LICENSE)

**Public beta: 0.14.0-beta.1.** Independent project, not officially affiliated with Nous Research, RyzeAPI or WhatsApp. Bring your own RyzeAPI account and configured Hermes installation. No credentials, hosting or model subscription are included. Dashboard labels and bundled skill instructions currently use Brazilian Portuguese; the README and installation guide are bilingual.

## An alternative to the built-in WhatsApp channel

You can use this plugin **instead of Hermes' built-in Baileys-based WhatsApp channel for supported workflows**, keeping Hermes as your agent and connecting WhatsApp through your own RyzeAPI account. No Hermes core patches are needed. This is not Meta's official WhatsApp Business Cloud API integration.

**This beta does not provide complete feature parity with the built-in channel.** Poll vote handling, automatic clarification-as-poll and recovery of quoted media attachments are not fully equivalent or validated here. Read the [comparison and migration checklist](docs/INSTALL.md#migrating-from-built-in-whatsapp) before switching workflows that depend on them.

## What's included

- Task-oriented dashboard: overview, instances, metrics and settings; QR pairing with connection-state feedback.
- One active instance as the Hermes channel, plus a list of other account instances—not multiple simultaneous AI channels.
- Contact and group firewall: listen/archive only or listen/respond; mentions/replies or all messages; authorized contacts or all group members.
- Message buffer, media handling, audio transcription and optional transcript echo.
- Private group/date archives and membership change records, without automatic history import.
- 14 sending tools: text, media, sticker, contact, location, PIX, buttons, list, carousel, form, poll, event, reaction and Status.
- Button/list reply correlation, persistent SQLite queue and deduplication across WebSocket and webhook.

## Installation

Initial support: **Linux with user-level systemd**, Python 3.12+ in the Hermes environment, and gateway/dashboard running under the same user and Hermes profile. Oracle and Cloudflare are not required. Dashboard authentication must be provided by Hermes or your proxy; never expose it without authentication.

Use the Python interpreter from your Hermes environment and replace `/path/to/profile` with your active profile:

```bash
hermes plugins install NeritonDias/hermes-ryzeapi --no-enable
hermes plugins list
python -m pip install -r /path/to/profile/plugins/ryzeapi/requirements.txt
hermes plugins doctor /path/to/profile/plugins/ryzeapi --ci
hermes plugins enable ryzeapi
```

The tested native installer does **not** install Python dependencies automatically. Follow the **[complete installation guide](docs/INSTALL.md)** before enabling WhatsApp: configure authentication, HTTPS webhook routing, credentials and the firewall. No recipients are allowed by default.

Review code and scanner findings before enabling a plugin: it runs with the Hermes process permissions. Installing from GitHub does not mean it has been approved by the official catalog. For an immutable install, use `--ref` with the release's full commit SHA; see [updates and removal](docs/INSTALL.md#updates-and-removal).

## Two skills installed automatically

When the enabled plugin loads, it registers and makes both skills available in the active profile—**no separate skill installation required**:

| Skill | Purpose |
| --- | --- |
| `ryzeapi` | Conversation/API workflows, messaging, instance operations and diagnostics. |
| `ryzeapi-painel` | Dashboard setup, navigation and verification. |

Start a new session and check `skills_list`, `/ryzeapi` and `/ryzeapi-painel`. Namespaced copies, `ryzeapi:ryzeapi` and `ryzeapi:ryzeapi-painel`, are also available. Both are discoverable across channels; Hermes loads the relevant instructions when needed, not both bodies on every message.

Updates preserve customized skills: local edits and name conflicts are not overwritten and generate a warning. See the [managed update lifecycle](docs/INSTALL.md#updates-and-removal).

Skills do not implement missing tools or grant permissions. Their API map includes operations not yet exposed in this beta. Direct account-administration tools in chat remain pending.

## Message tools

Synthetic `ryzeapi_send_buttons` example:

```json
{
  "number": "5511999999999",
  "request_id": "unique-test-001",
  "payload": {
    "contentText": "How can I help?",
    "buttons": [
      {"id": "help", "displayText": "Help me", "type": "REPLY"}
    ]
  },
  "dry_run": true
}
```

Remove `dry_run` only for an authorized destination and content. An `accepted` result means the API accepted the request, not that WhatsApp delivered or rendered it.

## Important limitations

- **Instance management:** dashboard creation is part of the selection flow while the channel is paused. An independent create-instance action and account-administration tools in chat are not included in this beta.
- **Carousel:** experimental. A real rendering failure occurred; the image-based variant still lacks conclusive confirmation.
- **Buttons/lists:** observed reply formats are covered by automated correlation tests; final human confirmation of the renewed response cycle remains pending.
- **Interactive returns:** not all poll votes, form responses and event attendance returns are validated. Sending a format does not imply handling every incoming event.
- **Media:** the current pipeline has an 8 MiB limit. Transcription depends on Hermes configuration and has timeouts/limits; unlimited audio is not promised.
- **Groups:** allowing every member to trigger the agent exposes its enabled tools. Use trusted groups and minimum permissions; messages and attachments are untrusted input.
- **PIX:** displays a key for copying; does not perform payments, create charges or verify receipt. Status requires specific authorization for content and audience.
- **Delivery:** no exactly-once guarantee. Uncertain operations are not automatically retried; inspect their records first.
- **Menus:** correlation expires after seven days. COPY/URL/CALL actions do not necessarily generate reply messages.
- **Compatibility:** tested against Hermes commit `a982d2c882ce14aca6e98873b32d3dce8a496a27`. Other versions and operating systems need testing.

## Versions and releases

Current version: **[v0.14.0-beta.1](https://github.com/NeritonDias/hermes-ryzeapi/releases/tag/v0.14.0-beta.1)**. This is a **public beta**, not a stability or full-parity guarantee. The GitHub release is designated Latest for visibility; the version name and release notes retain the beta warning.

Privacy maintenance: the initial public history and old archive were sanitized to replace a partially anonymized test fixture. Commit hashes and archive checksums changed; use a fresh clone/download if you obtained the initial release.

## Development and support

[Installation](docs/INSTALL.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Validation](docs/VALIDATION.md)

Open an issue with your version, OS, reproduction steps and **sanitized logs**. Never publish tokens, QR codes, SSH keys, personal phone numbers, private conversations or databases. This project does not imply official support from RyzeAPI or Nous Research.

Official documentation: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/) · [RyzeAPI documentation](https://docs.ryzeapi.cloud/).
