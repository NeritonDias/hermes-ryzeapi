# Changelog

## 0.14.3

Fixed the voice worker importing the plugin’s tools module instead of Hermes transcription tools. The receiver reports redacted STT failure categories and respects disabled transcription. A local whisper.cpp command adapter normalizes voice notes for CPU inference on self-hosted installations.

## 0.14.2

The new Webhooks page uses the public URL of the installed Hermes profile. It shows remote registration and both ends of the WebSocket connection, lets the owner edit the paused receiver, and copies its callback address. On the official Coolify/s6 image, the gateway can gracefully apply changes after returning the management response.

The Webapp reports activation blockers for the selected instance. The receiver subscribes to all six RyzeAPI event families via webhook and WebSocket. Call and label notifications are observed without triggering replies. WebSocket provisioning handles a new instance with no saved settings, reordered subscriptions and an existing all-events subscription. The plugin manages its own label and endpoint. Other destinations retain their own subscriptions.

## 0.14.1

Saving contact permissions and group policies works while the channel is paused. Activation is a separate action. The overview shows saved permission counts. The provider's group event settings are applied when the channel is activated.

## 0.14.0 — 2026-11-24

Stable Hermes v0.23.4 release. The Webapp and Dashboard share a responsive control panel. Coolify deployments use an internal listener on 9131 and explicit gateway redeploy. The controller reconciles webhook ownership, and outbound file reads are confined to the profile attachment directory. Inbound and outbound idempotency remain durable.


## 0.14.0-beta.1 — 2026-09-15

The public version remains **0.14.0-beta.1**. A mistakenly numbered release was withdrawn. Version metadata, documentation, tag and archive have been corrected together. The release is displayed as Latest on GitHub for visibility, but remains explicitly labeled a public beta.

The archive was rebuilt after owner-authorized privacy maintenance and this version correction. Use a fresh clone/download; previous hashes/checksums no longer identify the current package.

### Documentation and packaging corrections

- English primary README with a visible PT-BR language button.
- Full installation guides in English and Brazilian Portuguese, including dependencies, secure deployment, pairing, firewall, both bundled skills, validation, troubleshooting, updates and removal.
- Native WhatsApp replacement positioning, an explicit feature-parity comparison and a migration/rollback checklist.
- English security, contribution and validation documentation.
- Synchronized plugin, dashboard and bundled skill version metadata; documentation consistency tests.
- Replace an invalid-number test fixture with a fully synthetic sample.

This is a documentation/packaging release. It does not add account-administration tools, an independent instance-creation flow, carousel validation or missing native WhatsApp features. The automatic installation mechanism for both skills is unchanged.

### Initial feature set

First public distribution of the community plugin by Neriton Dias.

- Plugin/dashboard independent of the author's domain and infrastructure.
- Two skills, ryzeapi and ryzeapi-painel, registered and installed automatically when the enabled plugin loads.
- Managed skill updates with backups and preservation of local edits/conflicts.
- External configuration of public origin, webhook, listener port and service.
- 14 native sending tools, contact/group firewall, passive archives, buffering and optional transcript echo.
- Persistent WebSocket with webhook fallback, persistent queue and deduplication.
- Button/list correlation for observed reply formats, scoped to instance/chat with expiry.
- Tests, installation/security documentation and MIT license.

### Declared limitations

Carousels and some interactive returns need additional real-world validation. Skills map all RyzeAPI endpoint families, but executable coverage is not complete. Direct account management through chat and an independent dashboard create-instance flow remain pending; their experimental code is not included.
