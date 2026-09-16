# Changelog

## 1.0.0-beta.1 — 2026-09-15

Standardize the public 1.0 beta release line. **Still a prerelease, not stable 1.0.0.** The previous v0.14.0-beta.1 tag name is retained; its history and archive were rebuilt during owner-authorized privacy maintenance. Use a fresh clone/download; previous hashes/checksums no longer identify the sanitized release.

- English primary README with a visible PT-BR language button.
- Full installation guides in English and Brazilian Portuguese, including dependencies, secure deployment, pairing, firewall, both bundled skills, validation, troubleshooting, updates and removal.
- Native WhatsApp replacement positioning, an explicit feature-parity comparison and a migration/rollback checklist.
- English security, contribution and validation documentation.
- Synchronized plugin, dashboard and bundled skill version metadata; documentation consistency tests.
- Replace an invalid-number test fixture with a fully synthetic sample.

This is a documentation/packaging release. It does not add account-administration tools, an independent instance-creation flow, carousel validation or missing native WhatsApp features. The automatic installation mechanism for both skills is unchanged.

## 0.14.0-beta.1 — 2026-09-15

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
