# Operar por conversa

Use o mesmo procedimento em CLI, chat web e canais de mensagens. A resposta ao pedido volta pelo Hermes ao canal de origem; um envio solicitado à RyzeAPI tem seu próprio destino WhatsApp.

## Caminho curto

1. Extraia ação, instância, destino e conteúdo. Reutilize escolhas explícitas do contexto atual; pergunte somente o que faltar.
2. Descubra a ferramenta pelo verbo e domínio e leia seu schema.
3. Execute com credenciais internas ao plugin e contexto original da sessão. Não transforme uma operação disponível em exploração de arquivos ou login no painel.
4. Confirme pelo resultado. Para criação/configuração, consulte o estado quando houver ferramenta de leitura. Aceite de envio não é entrega.

As ferramentas de mensagens atuais usam a instância selecionada no plugin, sem seletor arbitrário no payload. Se o usuário pedir outra, descubra se existe operação instalada que suporte isso sem trocar o canal ativo; se não existir, declare a limitação. Não troque a instância silenciosamente.

## Decisões por intenção

| Pedido | Procedimento |
| --- | --- |
| “Envie Bom dia ao contato autorizado X” pelo Telegram | Ferramenta RyzeAPI de texto com destino WhatsApp explícito; confirmação no Telegram. Nunca usar ID do Telegram como telefone. |
| “Crie a instância suporte” | Descobrir gestão de instâncias; criar somente suporte, respeitando cota/confirmação do schema. Não selecionar, conectar ou gerar QR. |
| “Mande aqui botões de confirmação” num grupo RyzeAPI | Envio nativo ao próprio grupo, respeitando sua política. Não navegar nem imitar com texto. |
| “Veja os votos da enquete” | Identificar enquete/chat/instância e descobrir consulta de votos. Enviar enquete não implica suporte à leitura de votos. |
| “Só ouça o grupo Equipe” | Identificar grupo e descobrir operação de política do plugin. Não confundir com configuração global da API. |
| “Onde ajusto o buffer?” | Modo painel: explicar o caminho, sem alterar o valor. |

## Ferramenta ausente ou operação negada

Faça descoberta específica e confira a referência pertinente. Um recurso pode existir na API e não estar exposto pela instalação; declare essa diferença. Não invente ferramentas nem diga que a API não suporta algo só por faltar uma ferramenta.

Um helper de API só pode ser usado se realmente vier com o plugin, estiver documentado e aplicar a mesma autorização. Esta skill não declara um executor genérico existente. Não improvise um cliente privilegiado lendo tokens pelo terminal.

Credencial ausente exige configuração segura pelo operador. Permissão negada exige explicar a restrição e preservar o estado. Ferramenta desabilitada exige habilitação pelo operador; não modifique permissões para completar a tarefa.

## Identidade e escopo

Um ID de Telegram/Discord não prova identidade de operador RyzeAPI. Use o contexto autenticado do Hermes e respeite a política aplicada por cada ferramenta. Não falseie plataforma, remetente ou grupo. Ser membro de grupo autorizado não dá administração da conta.

Para lotes, resolva destinos/conteúdo ambíguos antes de executar. Não amplie “este grupo” para todos. Interrompa em resultado incerto, sem recriar IDs para duplicar envios.
