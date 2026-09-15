# Validação da beta 0.14.0-beta.1

Data: 2026-09-15. Hermes a982d2c882ce14aca6e98873b32d3dce8a496a27; Linux ARM64; Python 3.12.14.

## Resultado do pacote

- 217 testes automatizados aprovados em 24,001 s, em perfil temporário, sem credenciais de produção.
- Plugin Doctor aprovado: importação, manifesto e registro nativo; 14 ferramentas.
- Plugin compat aprovado: sem imports detectados na lista de remoção do Hermes.
- Instalação das duas skills, idempotência, atualização gerenciada/backup, conflito de nome, edição local, referência extra, rejeição de symlink e rollback de falha: cobertos por testes.
- Parser/linter Hermes, skills_list, skill_view, referências e /ryzeapi + /ryzeapi-painel: aprovados.
- Browser sintético: 23 cenários de tarefas e 25 de grupos aprovados, sem erros de página; rede bloqueada. Viewports desktop e móvel.
- Gitleaks 8.30.1: nenhum segredo detectado no diretório público.

O scanner nativo do Hermes emitiu CAUTION para fixtures sintéticas e comandos de testes/CI. Achados revisados: tokens de teste, entradas inválidas para testar rejeição, endereço loopback e instalação/execução de testes. Não foram removidos testes para esconder o aviso. Leia o relatório antes de aceitar uma instalação.

## Testes conversacionais

A versão anterior do refino, com uma skill e referência de painel, foi testada em três sessões reais Hermes. Os traces e limites estão em [SKILL-VALIDATION.md](SKILL-VALIDATION.md).

Nesta release o painel tornou-se uma segunda skill; sua instalação e carregamento são validados pelo carregador nativo. Não confundir teste de descoberta/decisão com execução real de cada endpoint.

## Não comprovado por esta suíte

- Instalação em outro sistema operacional ou compatibilidade com todo commit futuro do Hermes.
- Transporte real pelo Telegram/Discord ou autorização administrativa em todos os canais.
- Entrega/renderização de todos os formatos em todos os clientes WhatsApp.
- Correlação humana final do ciclo de botões/listas da versão anterior, carrosséis com mídia e todos os retornos de formulários/votos/eventos.
- Disponibilidade de toda operação do catálogo RyzeAPI como ferramenta instalada.

Testes não publicaram Status, não realizaram pagamentos e não criaram instâncias reais. A beta não foi auditada por terceiros e não é uma integração oficial.
