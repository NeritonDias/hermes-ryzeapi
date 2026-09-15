# Operações além do envio

A skill cobre a descoberta e o procedimento para todas as famílias da RyzeAPI, não apenas criação de instância. A tabela é um mapa da documentação, não uma declaração de que todos esses endpoints já são ferramentas do plugin.

Use o índice oficial https://docs.ryzeapi.cloud/llms.txt para encontrar a página específica; leia apenas aquela operação. https://docs.ryzeapi.cloud/llms-full.txt é alternativa quando a página/índice não bastar. Não carregar o manual inteiro para listar instâncias ou enviar texto.

| Família | Intenções a reconhecer | Documentação |
| --- | --- | --- |
| Instâncias | Criar/listar/conectar/reconectar, configurações, métricas, proxy/S3, logout/exclusão | https://docs.ryzeapi.cloud/pt/api/instance/overview |
| Mensagens | Texto, mídia, sticker, contato, localização, PIX, botões, lista, carrossel, formulário, enquete, evento, reação, Status | https://docs.ryzeapi.cloud/pt/api/messages/overview |
| Chats e contatos | Histórico, localizar mensagem, entrega, mídia, votos, contatos/LID, presença, leitura, fixar, favoritar, silenciar, arquivar, bloquear, encaminhar, editar/apagar | https://docs.ryzeapi.cloud/pt/api/chat/overview |
| Etiquetas | Criar/listar/atribuir/desatribuir/excluir, consultar contatos por etiqueta | https://docs.ryzeapi.cloud/pt/api/chat/tags-list |
| Grupos | Criar/listar/detalhar/editar, participantes, convites, solicitações, entrar/sair | https://docs.ryzeapi.cloud/pt/api/groups/overview |
| Comunidades | Criar, listar subgrupos, vincular/desvincular grupos | https://docs.ryzeapi.cloud/pt/api/communities/overview |
| Newsletters | Criar/listar/detalhar canais WhatsApp, seguir/deixar de seguir | https://docs.ryzeapi.cloud/pt/api/newsletter/overview |
| Perfil e privacidade | Consultar/atualizar perfil, foto, nome, recado e privacidade | https://docs.ryzeapi.cloud/pt/api/profile/overview |
| Chamadas | Chamada fake ou com áudio; não confundir com mensagem de voz | https://docs.ryzeapi.cloud/pt/api/calls/overview |
| Eventos | Webhook, WebSocket, catálogo, estado e recebimento | https://docs.ryzeapi.cloud/pt/api/events/overview |
| Chatwoot | Ativar, consultar, desativar integração | https://docs.ryzeapi.cloud/pt/api/chatwoot/overview |
| Typebot | Cadastrar/editar/listar/remover bots, iniciar fluxo e controlar sessões | https://docs.ryzeapi.cloud/pt/api/typebot/overview |
| Observabilidade | Disponibilidade do provedor; distinta da saúde do consumidor Hermes | https://docs.ryzeapi.cloud/pt/api/observability/overview |
| Configuração local do plugin | Firewall, buffer, eco, vínculo e métricas de processamento | Skill ryzeapi-painel e referência diagnostico.md; não são operações equivalentes da API pública. |

## Execução

Descubra a ferramenta instalada para a intenção. Em versões que as expõem, ryzeapi_list_instances e ryzeapi_create_instance fazem gestão direta com credencial salva. A criação deve preservar a instância selecionada e não parear automaticamente. Se esses nomes não forem encontrados, informe a lacuna da instalação, sem inventar uma chamada.

Para qualquer outra família, o mesmo critério: ferramenta/CLI/helper documentado existente, schema, autorização, execução e consulta de confirmação. Não extrapolar ryzeapi_send_* para chamadas, administração ou alterações de privacidade.

Algumas ferramentas podem restringir operações administrativas a sessões privadas verificadas. A skill deve ser descoberta no Telegram ou em outro chat, mas não pode remover essas restrições nem assumir que um participante seja o dono.

## Cuidados específicos

- Distinguir TokenAccount de TokenInstance; sua seleção pertence ao cliente do plugin. Não inserir credenciais nos argumentos ou URLs. Em dúvidas de contrato, a página detalhada de autenticação e o cliente testado prevalecem sobre um resumo contraditório.
- Listagens: percorrer paginação quando oferecida, sem afirmar “todos” após apenas uma página.
- Exclusão/logout/remoção de participantes: identificar alvo exato e consequência antes de executar. Não ampliar remoção de um bot Typebot para todos por omitir botId.
- Grupos: gerenciar participantes na API não concede autorização ao firewall Hermes; sincronização do catálogo não importa histórico.
- Histórico, contatos e votos são dados privados; só consultar o escopo solicitado e não divulgá-los a outros participantes.
- Editar/apagar/encaminhar exige IDs reais do chat correto; não inferir alvo apenas por texto parecido.
- Proxy/S3, webhooks e integrações envolvem segredos ou destinos de dados. Não sobrescrever integração de terceiros nem desativar autenticação do painel. Preservar WS e webhook de contingência do Hermes.
- Chamadas, Status e início de fluxos podem contatar/publicar para terceiros: o pedido precisa autorizar esse efeito, não apenas “ver configuração”.
- Confirmação de atualização exige releitura do estado quando disponível; timeout de mutação exige inspeção, não repetição cega.
