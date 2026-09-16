# Installation and operation

[![English](https://img.shields.io/badge/Language-English-196b62)](INSTALL.md) [![Português (Brasil)](https://img.shields.io/badge/Idioma-PT--BR-196b62)](INSTALL.pt-BR.md)

[Back to README](../README.md) · Distribution **0.14.0-beta.1**.

## Prerequisites

- Linux, Python 3.12+, and Hermes Agent installed and configured with your model provider.
- Gateway and dashboard running under the same user and Hermes profile. Initial support targets user-level systemd.
- Your own RyzeAPI account, available instance quota and an authorized WhatsApp account to pair.
- An authenticated dashboard and a public HTTPS webhook. You provide domains, edge routing, certificates and authentication.

Tested Hermes baseline: `a982d2c882ce14aca6e98873b32d3dce8a496a27`. This plugin does not install models, provide hosting or use the author's account.

## Install

Review code and permissions first: a Python plugin runs with the Hermes process's access.

```bash
hermes plugins install NeritonDias/hermes-ryzeapi --no-enable
hermes plugins list
```

The installed directory is `plugins/ryzeapi` in your active profile, usually `~/.hermes/plugins/ryzeapi`, regardless of the repository name. Replace `/path/to/profile` below with that profile. **Python dependencies are not installed automatically on the tested Hermes baseline.** Use the Python interpreter belonging to your Hermes environment, not a global Python:

```bash
python -m pip install -r /path/to/profile/plugins/ryzeapi/requirements.txt
hermes plugins doctor /path/to/profile/plugins/ryzeapi --ci
hermes plugins compat /path/to/profile/plugins/ryzeapi
hermes plugins enable ryzeapi
```

Dependencies are declared in the manifest. Do not ignore environment conflicts; use an isolated Hermes installation/profile before upgrading.

The native Hermes scanner may report **CAUTION** for synthetic test tokens, invalid security-test paths and test/CI commands. Review the findings; the documented fixtures are not real credentials. Accept interactively only after trusting the reviewed code. For reviewed automated installation, `--force` accepts caution findings; never use it to bypass unknown findings or a dangerous verdict.

On the first load of the enabled plugin, `ryzeapi` and `ryzeapi-painel` are installed into the profile's `skills/` directory and registered under the plugin namespace. Open a new session and check `skills_list`. Installing with `--no-enable` leaves the plugin inactive until enabled.

## Configure deployment

Run `scripts/configure.py` with the Hermes Python interpreter. It writes only non-secret deployment options to the profile's `ryzeapi/deployment.json`, with mode 0600:

```bash
python /path/to/profile/plugins/ryzeapi/scripts/configure.py \
  --public-origin https://ia.example.com \
  --webhook-url https://hooks.example.com/ryzeapi/events \
  --listener-port 9120 \
  --gateway-service hermes-gateway.service \
  --webhook-label hermes-ryzeapi \
  --check
```

Replace the example values, then remove `--check` to save. Restart dashboard/gateway during an idle window to apply deployment configuration. The service name must be your actual gateway's user-systemd service, not a shell command. This script does not provision DNS, TLS, proxy rules or systemd units.

Proxy requirements:

- Keep the dashboard behind authentication, such as Hermes authentication or an access provider at the proxy. The plugin's Origin/`x-ryze-ui` checks do **not** authenticate users.
- Preserve the configured public Origin and route dashboard requests to its local upstream.
- Publish only **POST /ryzeapi/events** from the configured loopback listener, over HTTPS, preserving the Authorization header. RyzeAPI sends the secret configured by the plugin.
- Do not put interactive login challenges on the webhook route. Do not expose `/health`, `/maintenance`, the whole listener port, databases or configuration files.
- Allow outbound HTTPS and WSS to RyzeAPI. The listener must not bind to a public interface.

Any infrastructure meeting this contract can be used; Oracle and Cloudflare are not dependencies. Do not disable dashboard authentication to make the webhook work.

## Account, WhatsApp and firewall

1. Open RyzeAPI in the authenticated dashboard. Enter a TokenAccount for listing/creating instances, or TokenInstance for an existing instance. Secrets are stored privately in `ryzeapi/settings.json`, outside the plugin code.
2. Select the instance explicitly. In this beta, creation is part of the create/select flow while the channel is paused, not an independent action while it is active.
3. Generate a QR/pairing code in a private surface and pair your device. Wait for a confirmed connected state, not merely a generated QR.
4. Configure allowed contacts. **Receber** permits replies/sends; **Comandar** permits execution. No contact is allowed by default.
5. For groups, synchronize the catalog, select groups and explicitly confirm each policy. **Só ouvir** archives passively. Allowing all group members to trigger the agent gives them access to its enabled tools; use trusted groups.
6. Configure the buffer and transcript echo. Enable the channel; verify WebSocket/webhook, consumer health and permissions.
7. Run an authorized real test and verify both successful delivery and rejection of unauthorized senders.

If chat tools are missing, check the `ryzeapi` toolset in that session/profile's tool configuration. Skills do not enable tools or bypass authorization. Dashboard labels currently use Brazilian Portuguese.

## Validate the installation

- `hermes plugins list`: RyzeAPI loaded without errors.
- New session: both skills in `skills_list`; references readable through `skill_view`.
- Run the reproducible check with the Hermes Python interpreter:

```bash
python /path/to/profile/plugins/ryzeapi/scripts/verify_install.py
```

The verifier checks both skills and 14 registered tools without calling RyzeAPI. It does not prove live connectivity.

- Dashboard: connected account and healthy consumer; a connected WebSocket alone is insufficient.
- A `dry_run` send validates without an external POST.
- An authorized real send should be checked for acceptance, message ID and delivery/rendering appropriate to the format. Do not automatically retry on a timeout.

## Migrating from built-in WhatsApp

The plugin can replace Hermes' built-in Baileys-based channel for supported workflows without changing Hermes core. It is not Meta's official WhatsApp Business Cloud API adapter. **Complete feature parity is not promised in this beta.**

| Capability | This plugin |
| --- | --- |
| Conversations, images, documents and audio | Adapter implemented; STT depends on Hermes and media limits apply. |
| Groups and access control | Own policies, including passive archives, mentions and authorized members. Reconfigure permissions. |
| Sending polls | Tool available; returned votes and automatic clarification-as-poll do not have complete parity. |
| Quoted attachments | Complete file recovery is not validated. |
| Streaming edits, read receipts and self-chat mode | Not claimed equivalent; validate required workflows before switching. |
| Existing sessions, allowlists and cron destinations | Not automatically migrated from `whatsapp` to `ryzeapi`. |

This comparison uses the [official built-in WhatsApp documentation](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp), consulted on September 15, 2026, and this release's code. Recheck when upgrading Hermes.

1. Make a private configuration backup and preserve the native session credentials. Never share that backup.
2. Configure RyzeAPI and its firewall with the channel paused. Native session credentials are not imported; pair through RyzeAPI.
3. During an idle window, disable the native WhatsApp channel in gateway configuration. If enabled through `.env`, set `WHATSAPP_ENABLED=false`; check profile overrides too. Do not disable Telegram or unrelated channels.
4. Enable RyzeAPI and restart the necessary processes. Avoid two adapters responding through the same WhatsApp account.
5. Explicitly review home-channel/cron destinations and permissions for `ryzeapi`. Test the DMs, groups, attachments, voice and scheduled tasks you actually use.
6. To roll back, pause/disable RyzeAPI before re-enabling the native channel. Do not overwrite new SQLite queues with old backups or repeat sends with uncertain outcomes.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing dashboard tab or tools | Same user/profile, enabled plugin, dependencies, Doctor and dashboard/gateway restart. |
| Missing skills | Plugin loaded, new session and conflict warnings; run `scripts/verify_install.py`. |
| Connected, but no reply | Consumer health, selected instance, firewall and group mention policy. WebSocket connectivity does not prove processing. |
| No webhook events | Exact HTTPS route, preserved Authorization and no interactive authentication on that route only. |
| Expired QR | Generate a fresh QR privately; never post a screenshot. |
| Accepted send, no visible message | Inspect message ID, receipts and format limitations. Do not automatically resend after timeout. |

Share sanitized logs only. Never publish `settings.json`, QR codes, tokens, databases or conversations.

## Updates and removal

Back up configuration and data privately before updating. Pause the channel and wait for in-flight tasks; pausing does not cancel tasks already accepted. Do not overwrite a current database with an old one during rollback.

Native update:

```bash
hermes plugins update ryzeapi
python -m pip install -r /path/to/profile/plugins/ryzeapi/requirements.txt
hermes plugins doctor /path/to/profile/plugins/ryzeapi --ci
hermes plugins compat /path/to/profile/plugins/ryzeapi
```

Restart processes that load the plugin during an idle window and inspect both skills in a new session. These commands follow your installed source; they are not a guarantee of a pinned release. For an immutable installation, the installer accepts `--ref` with a full 40-character commit SHA. Use the commit associated with the release, not a tag name in place of that SHA.

The managed skill installer stores ownership hashes in `ryzeapi/skill-install.json`. Unmodified copies are updated with backups under `ryzeapi/skill-backups/`. Local edits and extra files create a conflict and are preserved. Review/back up your customizations before removing a conflicting copy; reloading can then install the bundled version. Namespaced versions remain available without replacing your edits.

Disable before removing:

```bash
hermes plugins disable ryzeapi
hermes plugins uninstall ryzeapi
```

Check prompts/options in your installed Hermes version. Disabling/removing the plugin does not delete your RyzeAPI account, paired device, private data or exported skills. Remove `ryzeapi` and `ryzeapi-painel` through the skill manager if desired, after preserving customizations. Conversation archives and SQLite files need your own retention policy.
