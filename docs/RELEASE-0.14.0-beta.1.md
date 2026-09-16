# Hermes × RyzeAPI v0.14.0-beta.1

**Public beta — not a production-stability guarantee.**

Author: **Neriton Dias** · [Instagram @neritondias](https://www.instagram.com/neritondias/).

## English

- English README with a PT-BR language button and matching installation tutorials.
- Installation covers manual Python dependencies, secure deployment, automatic loading of both skills, pairing, firewall, testing, troubleshooting and upgrades/removal.
- Documentation explains how RyzeAPI can replace the built-in WhatsApp channel for supported workflows, with an explicit comparison and migration/rollback checklist. Full native feature parity is **not** claimed.
- Both bundled skill versions match the plugin/dashboard: 0.14.0-beta.1.
- This is a documentation/packaging update; pending runtime features remain pending. The correct version is v0.14.0-beta.1; the mistakenly numbered release was withdrawn.

Read the [README](../README.md), [installation guide](INSTALL.md) and [validation scope](VALIDATION.md) before installing. No separate skill installation is needed: enable and load the plugin, then start a new session.

## Português (Brasil)

- README principal em inglês com botão PT-BR e tutoriais de instalação nos dois idiomas.
- Guia cobre dependências Python, publicação segura, carregamento automático das duas skills, pareamento, firewall, testes, diagnóstico, atualização e remoção.
- Explica como substituir o canal WhatsApp nativo nos fluxos suportados, com comparação e roteiro de migração/retorno. **Não promete todas as funcionalidades do nativo.**
- Plugin, painel e duas skills identificados como 0.14.0-beta.1.
- Atualização de documentação/empacotamento: recursos pendentes continuam pendentes. A versão correta é v0.14.0-beta.1; a release com numeração incorreta foi retirada.

Leia o [README PT-BR](../README.pt-BR.md) e o [tutorial PT-BR](INSTALL.pt-BR.md). As duas skills são instaladas automaticamente ao carregar o plugin habilitado; abra uma nova sessão.

## Verification

The updated isolated suite passed 221 tests on Linux ARM64 (23.703 seconds), including the four new documentation/version checks. No live WhatsApp sends were made for this release.

See the published release for the final commit, CI results and archive checksum. This source document does not contain a self-referential commit hash.

No production service restart, real messages or account changes are required by this documentation release.

GitHub presentation: this release is marked Latest so its version appears in the repository sidebar. The beta designation and limitations still apply. / A marcação Latest permite exibir a versão no resumo do repositório; o aviso de beta e os limites continuam válidos.
