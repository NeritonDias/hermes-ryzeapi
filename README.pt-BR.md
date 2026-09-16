# Hermes × RyzeAPI

[![English](https://img.shields.io/badge/Language-English-196b62)](README.md) [![Português (Brasil)](https://img.shields.io/badge/Idioma-PT--BR-196b62)](README.pt-BR.md)
[![Release](https://img.shields.io/github/v/release/NeritonDias/hermes-ryzeapi?include_prereleases)](https://github.com/NeritonDias/hermes-ryzeapi/releases)
[![Tests](https://github.com/NeritonDias/hermes-ryzeapi/actions/workflows/test.yml/badge.svg)](https://github.com/NeritonDias/hermes-ryzeapi/actions/workflows/test.yml)

Plugin comunitário de WhatsApp para **Hermes Agent**, com painel web, duas skills integradas, WebSocket permanente e webhook de contingência.

**Autor: Neriton Dias** · [Instagram @neritondias](https://www.instagram.com/neritondias/) · [MIT](LICENSE)

**Beta pública: 1.0.0-beta.1.** Projeto independente, sem afiliação oficial com Nous Research, RyzeAPI ou WhatsApp. Requer sua própria conta RyzeAPI e um Hermes configurado; este repositório não inclui credenciais, hospedagem nem assinatura de modelo. Painel e instruções das skills estão em PT-BR; README e instalação têm versões em inglês e português.

## Alternativa ao WhatsApp nativo do Hermes

Você pode usar este plugin **no lugar do canal WhatsApp nativo baseado em Baileys** para os fluxos suportados, mantendo o agente Hermes. A conexão passa pela sua conta RyzeAPI. Não é a integração oficial WhatsApp Business Cloud API da Meta e não exige patches no núcleo do Hermes.

**Esta beta não oferece paridade completa com o módulo nativo.** Veja a [comparação e o roteiro de migração](docs/INSTALL.pt-BR.md#migrar-do-whatsapp-nativo). Enquetes com votos de retorno, perguntas de esclarecimento transformadas automaticamente em enquetes e recuperação de anexos de mensagens citadas não têm equivalência completa comprovada aqui. Não migre um fluxo que dependa desses recursos sem testá-lo.

## O que inclui

- Painel por tarefas: visão geral, instâncias, métricas e configurações; QR Code com acompanhamento de conexão.
- Uma instância ativa como canal do Hermes; listagem de outras instâncias da conta. Não são vários canais de IA simultâneos.
- Firewall de contatos e grupos: só ouvir/arquivar ou ouvir e responder; menções/respostas ou todas as mensagens; contatos autorizados ou todos os membros.
- Buffer de mensagens, mídia, transcrição de áudio e opção de exibir ou não a transcrição na conversa.
- Arquivo privado por grupo/data e registro de entradas/saídas, sem importar histórico automaticamente.
- 14 ferramentas de envio: texto, mídia, sticker, contato, localização, PIX, botões, lista, carrossel, formulário, enquete, evento, reação e Status.
- Correlação de cliques de botões/listas, fila SQLite persistente e deduplicação entre WebSocket e webhook.

## Instalação

Suporte inicial: **Linux com systemd de usuário**, Python 3.12+ no ambiente do Hermes, gateway e dashboard executados pelo mesmo usuário/perfil. Não depende de Oracle ou Cloudflare. A autenticação do dashboard é responsabilidade do Hermes/proxy; nunca exponha o painel sem autenticação.

```bash
hermes plugins install NeritonDias/hermes-ryzeapi --no-enable
hermes plugins list
python -m pip install -r /caminho/do/perfil/plugins/ryzeapi/requirements.txt
hermes plugins doctor /caminho/do/perfil/plugins/ryzeapi --ci
hermes plugins enable ryzeapi
```

Substitua `/caminho/do/perfil` pelo perfil ativo e use o Python do ambiente Hermes. As dependências Python não são instaladas automaticamente pelo comando nativo na base testada.

Antes de ativar o WhatsApp, siga **[o guia completo](docs/INSTALL.pt-BR.md)** para configurar seu domínio, webhook e serviço. O plugin começa fechado, sem destinatários liberados. Revisar código antes de habilitar: plugins executam com as permissões do processo Hermes. Instalação por GitHub não significa revisão pelo catálogo oficial.

Para fixar uma versão, use `--ref` com o SHA completo da release. Para atualização, prefira versões revisadas; consulte [atualização e remoção](docs/INSTALL.pt-BR.md#atualização-e-remoção).

## Versões e releases

Versão atual: **[v1.0.0-beta.1](https://github.com/NeritonDias/hermes-ryzeapi/releases/tag/v1.0.0-beta.1)**. `1 tag` no GitHub significa uma tag existente, não versão 1. O sufixo `beta.1` identifica uma pré-release, não uma versão 1.0.0 estável. A antiga `v0.14.0-beta.1` permanece disponível; a nova numeração não adiciona funcionalidades pendentes nem certifica paridade com o WhatsApp nativo.

## Duas skills instaladas automaticamente

Nota de privacidade: o histórico inicial e o pacote antigo foram saneados para substituir um dado de teste parcialmente anonimizado. Os hashes dos commits e do pacote mudaram; faça um novo clone/download se obteve a versão inicial.

Ao carregar o plugin habilitado, as duas skills são registradas e disponibilizadas no perfil ativo, **sem instalar skills separadamente**:

- **ryzeapi** — operação por conversa/API, mensagens, instâncias e diagnóstico.
- **ryzeapi-painel** — configuração, uso e verificação da interface.

Abra uma nova sessão e confira `skills_list`, `/ryzeapi` e `/ryzeapi-painel`. As cópias qualificadas `ryzeapi:ryzeapi` e `ryzeapi:ryzeapi-painel` também ficam disponíveis. Ambas são descobríveis em qualquer canal; o Hermes carrega o conteúdo pertinente quando necessário, não ambos em toda mensagem.

Atualizações preservam skills personalizadas: se houver alteração local ou conflito de nome, o plugin não sobrescreve a cópia e registra um aviso. Veja [o ciclo de atualização](docs/INSTALL.pt-BR.md#atualização-e-remoção).

As skills não substituem ferramentas nem concedem permissões. O mapa da API inclui recursos ainda não expostos nesta beta; uma instrução não implementa um endpoint ausente.

## Ferramentas de mensagens

```json
{
  "number": "5511999999999",
  "request_id": "meu-teste-unico-001",
  "payload": {
    "contentText": "Como posso ajudar?",
    "buttons": [{"id": "ajuda", "displayText": "Quero ajuda", "type": "REPLY"}]
  },
  "dry_run": true
}
```

Exemplo sintético para `ryzeapi_send_buttons`. Retire dry_run apenas com destino/conteúdo autorizados. `accepted` confirma aceite da API, não entrega/renderização.

## Limites importantes

- Gestão de instâncias: a criação no painel faz parte do fluxo de seleção com o canal pausado. O botão independente de criação e ferramentas administrativas de conversa ainda não entram nesta beta; não são apresentados como concluídos.
- Carrossel: experimental. Houve falha de renderização em teste real; a variante com imagens ainda não tem confirmação conclusiva.
- Botões/listas: correlação coberta por testes automatizados com o formato observado; a confirmação humana final do novo ciclo de resposta ainda está pendente nesta beta.
- Votos de enquete, respostas de formulário e presença em eventos não têm todos os retornos validados. Enviar um formato não significa interpretar todos os seus eventos.
- Mídias: limite de 8 MiB no pipeline atual. STT depende da configuração do Hermes, tem timeout e limites de transcrição; não há promessa de áudio ilimitado.
- Grupos: liberar todos os membros permite que eles acionem o agente e suas ferramentas; use apenas grupos confiáveis e permissões mínimas. Arquivos/conversas são dados não confiáveis.
- PIX apresenta chave para copiar; não executa pagamento, cobrança nem confirma recebimento. Status exige autorização explícita da audiência/conteúdo.
- Não há garantia de processamento/entrega exatamente uma vez. Operações incertas não são repetidas automaticamente; consulte os registros.
- Correlações de menus expiram em 7 dias. COPY/URL/CALL não produzem necessariamente uma mensagem de resposta.
- Beta validada contra o commit Hermes `a982d2c882ce14aca6e98873b32d3dce8a496a27`. Compatibilidade com outras versões/SOs precisa ser testada; não declaramos compatibilidade universal.

## Desenvolvimento e suporte

[Instalação](docs/INSTALL.pt-BR.md) · [Segurança](SECURITY.md) · [Contribuir](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Validação](docs/VALIDATION.md)

Abra uma issue com versão, sistema, passos e **logs sanitizados**. Nunca publique token, QR Code, chave SSH, telefone pessoal, conteúdo privado ou banco de dados. Não existe suporte oficial da RyzeAPI/Nous implícito neste projeto.

Documentação externa: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/) · [Documentação RyzeAPI](https://docs.ryzeapi.cloud/).
