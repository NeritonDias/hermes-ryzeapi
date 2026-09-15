# Contribuir

Autor: Neriton Dias (@neritondias). Licença MIT.

Abra uma issue com problema, versão e reprodução sanitizada. Mudanças devem ficar no plugin: não distribuir patches do núcleo Hermes nem credenciais/configurações pessoais.

## Testes

Use um checkout Hermes no commit documentado e o seu ambiente Python:

```bash
HERMES_SOURCE=/caminho/hermes-agent python scripts/test.py
hermes plugins doctor . --ci
hermes plugins compat .
```

scripts/test.py cria um perfil temporário e remove variáveis RYZEAPI_ da execução. A suíte usa respostas mockadas; não envia WhatsApp nem cria instâncias reais. Testes do carregador de skills usam componentes nativos Hermes.

As verificações visuais separadas estão em tests/test_ui_tasks.py e tests/test_ui_groups.py. Precisam de Playwright/Chromium e de RYZE_UI_HARNESS apontando para tests/ui_harness.jsx compilado com React/ReactDOM pelo esbuild. HERMES_SOURCE identifica o checkout. O harness intercepta rede e usa fixtures sintéticas. Esses testes não provam autenticação ou operação no provedor.

## Regras de mudança

- Preserve settings e dados fora do código, sem defaults de telefone/instância/domínio do autor.
- Teste firewall, correlação por chat/instância, idempotência e falhas antes de ampliar formatos.
- Não converter LID em telefone por remoção de sufixo.
- Não remover a contingência de webhook ou repetir mutação incerta.
- Atualize plugin.yaml, dashboard/manifest.json, documentação e testes juntos.
- Skill ryzeapi orienta conversa/API; ryzeapi-painel orienta interface. Não afirmar que uma ferramenta existe por estar na documentação pública.
- Teste instalação conjunta, atualização de cópias gerenciadas e preservação de edições locais.
- Não anexar bancos, dumps de eventos ou logs privados a PRs.

Faça um scan de segredos no diretório e no histórico antes de publicar. Resultado limpo de scanner não equivale a auditoria independente de segurança.
