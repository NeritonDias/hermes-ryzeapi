# Validação da skill RyzeAPI

Data: 2026-09-15. Skill 0.14.0; plugin público ainda candidato 0.14.0-beta.1.
Fontes: documentação oficial Hermes de Creating Skills, Skills System e Bundle skills.

## Verificado

- Parser e linter nativos Hermes: frontmatter aceito, sem avisos.
- Perfil temporário: skills_list encontra ryzeapi; skill_view abre o conteúdo e todas as seis referências; tentativa de caminho fora da pasta é rejeitada.
- Comando /ryzeapi gera uma invocação válida.
- Visibilidade no mecanismo nativo testada em 12 contextos de canal × 3 combinações de toolsets. Isso verifica ausência de filtros, não autenticação de todos os canais.
- Suíte do candidato público: 210 testes, aprovados em 24,294 segundos.

## Avaliação com o Hermes real

Três sessões novas na VPS, modelo configurado gpt-5.6-sol. Sem pré-carregar a skill, sem /ryzeapi e com somente o toolset skills habilitado. Os pedidos eram simulações explícitas sem efeitos externos, solicitando consulta às instruções pertinentes.

| Cenário | Chamadas observadas | Resultado |
| --- | --- | --- |
| Pedido descrito como recebido pelo Telegram para enviar enquete no WhatsApp | skill_view ryzeapi + conversa.md + mensagens.md | Indicou ryzeapi_send_poll, destino WhatsApp explícito, dados faltantes e nenhum login no painel. |
| Orientação no painel para grupo só ouvir | skill_view ryzeapi + painel.md | Separou sincronização de autorização; exigiu releitura após salvar/atualizar antes de afirmar persistência. |
| Criação, votos sem ferramenta, grupo pedindo contatos privados, envio incerto | skill_view ryzeapi + conversa.md + operacoes.md + mensagens.md + diagnostico.md | Preservou vínculo atual, reconheceu ferramenta ausente, negou acesso indevido e não propôs reenvio automático. |

Tempos observados entre mensagens de cada sessão: 17,60 s, 14,20 s e 21,65 s. Não são benchmark de criação de instância nem garantia de latência futura.

## Limites

Estes testes verificam instruções, descoberta e decisões do modelo. Não executam os endpoints de envio/criação, não provam transporte real pelo Telegram e não garantem acionamento perfeito em toda formulação.

O mapa de operações documenta todas as famílias da API, mas não implementa ferramentas ausentes. Ferramentas administrativas e acesso entre canais devem ter validação própria no backend; a skill não concede permissões.

A atualização instalada alterou somente Markdown da skill e referências, com backup, sem reiniciar serviços ou modificar configurações do canal. Conversas antigas podem manter instruções em cache.

O validador genérico Codex não aceita os campos Hermes author/version. Mantivemos o formato documentado pelo Hermes e usamos seu parser/linter como critério de compatibilidade do destino.
