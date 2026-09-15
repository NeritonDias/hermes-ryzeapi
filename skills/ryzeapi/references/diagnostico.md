# Diagnóstico mínimo por sintoma

Diagnosticar não autoriza reiniciar, reconfigurar, apagar banco ou reenviar mensagens. Consulte somente os metadados necessários, sem tokens, QR ou envelopes completos.

| Sintoma | Verificações |
| --- | --- |
| Skill não aparece | Instalação no perfil ativo, habilitação e índice de nova sessão. Registro apenas como plugin:skill não entra no índice automático. |
| Skill carregada, ferramenta ausente | Descoberta, versão instalada e toolsets habilitados na sessão; não é falha de login no painel. |
| WhatsApp conectado, sem resposta | Recebimento WS/webhook → identidade → firewall → buffer/fila → saúde do consumidor → agente → envio. |
| Grupo não responde à menção/clique | JID e política atual, identidade do bot/LID, menção/citação ou correlação de menu do mesmo chat. |
| Mensagens fora de ordem | Ordem de chegada, agrupamento por contato, preparação de mídia/STT e barreiras de comandos. Não ordenar pelo momento em que STT terminou. |
| Áudio sem transcrição visível | echo_transcripts pode estar desligado; verificar conteúdo interno/erro de STT sem alterar preferência. |
| Envio aceito não chegou | ID retornado, destinatário, recibo/consulta de entrega; não reenviar por ausência de recibo. |
| Configuração some ao atualizar | Resultado do salvamento, erro de leitura, instância escolhida; não substituir estado por vazio. |

## Estados e limites

- WebSocket conectado não comprova consumidor saudável. Webhook é contingência; eventos duplicados são deduplicados. WS não reconstrói eventos perdidos.
- Fila persistente: pending → preparing → handoff → admitted/uncertain. Handoff incerto não deve ser reproduzido automaticamente.
- /stop cancela itens anteriores ainda não admitidos; não desfaz efeitos já executados.
- Métricas de tempo se sobrepõem; não somá-las como latência total. Sem amostra não é zero.
- Grupo “Só ouvir” não aciona IA/STT/eco. Arquivos privados por instância/grupo/data surgem com atividade permitida; registram autoria disponível e eventos de membros. Não importam histórico nem todos os binários.
- LID exige vínculo verificado ao telefone. Aceitar variante brasileira com/sem nono dígito não autoriza interpretar dígitos de LID como telefone.
- O plugin não altera núcleo Hermes. Uma correção de skill não torna endpoints ainda ausentes executáveis nem muda permissões.

Relate a fronteira da falha com evidência: por exemplo, recebido e bloqueado pela política, aceito e entrega não confirmada, ou ferramenta não exposta. Não afirmar causa apenas pelo print.
