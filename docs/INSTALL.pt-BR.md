# Instalação e operação

[![English](https://img.shields.io/badge/Language-English-196b62)](INSTALL.md) [![Português (Brasil)](https://img.shields.io/badge/Idioma-PT--BR-196b62)](INSTALL.pt-BR.md)

[Voltar ao README](../README.pt-BR.md) · Distribuição **0.14.1**.

## Pré-requisitos

- Linux, Python 3.12+ e Hermes Agent já instalado/configurado com seu provedor de modelo.
- Gateway e dashboard no mesmo usuário e perfil Hermes. Suporte a Coolify/s6 e systemd de usuário.
- Conta RyzeAPI, cota disponível e WhatsApp autorizado para pareamento.
- Dashboard autenticado e webhook público HTTPS. Domínios, portas de borda, certificados e autenticação são responsabilidade da sua infraestrutura.

Ambiente validado para a v0.14.1: imagem oficial Hermes v0.23.4 em Linux ARM64. Este plugin não instala modelos, não fornece hospedagem e não usa uma conta do autor.

## Instalar

Revise o código e permissões: um plugin Python roda com acesso do processo Hermes.

```bash
commit=$(git ls-remote --refs https://github.com/NeritonDias/hermes-ryzeapi.git refs/tags/v0.14.1 | cut -f1)
hermes plugins install NeritonDias/hermes-ryzeapi --ref "${commit:?v0.14.1}" --no-deps --no-enable
hermes plugins list
```

Substitua `/caminho/do/perfil` pelo diretório do perfil ativo. Na imagem oficial v0.23.4, o padrão é `/opt/data` e o Hermes resolve as dependências ao habilitar o plugin. A linha de `pip` abaixo se aplica apenas a ambientes personalizados que gerenciam as dependências manualmente. Execute-a com o Python do Hermes.

```bash
# Somente para dependências gerenciadas manualmente em ambiente personalizado
# python -m pip install -r /caminho/do/perfil/plugins/ryzeapi/requirements.txt
hermes plugins doctor /caminho/do/perfil/plugins/ryzeapi --ci
hermes plugins enable ryzeapi
```

O manifesto declara as dependências. Não ignore conflitos com seu ambiente; isole um perfil/instalação antes de atualizar.

O scanner nativo Hermes pode emitir CAUTION nesta versão por fixtures de testes com tokens sintéticos/caminhos inválidos e pelos comandos de teste/CI. Revise os achados: não há credenciais reais nesses exemplos. Em terminal interativo, aceite somente se confiar no código revisado; para instalação automatizada revisada, --force aceita esse aviso de cautela. Não use isso para ignorar achados desconhecidos; veredito dangerous não deve ser contornado.

Na primeira carga do plugin habilitado, ryzeapi e ryzeapi-painel são copiadas de modo gerenciado para skills/ do perfil, e registradas também sob namespace. Abra uma nova sessão: skills_list deve listar ambas. Instalar com --no-enable deixa o código inativo até você habilitá-lo.

## Webapp Hermes e Coolify

No **Webapp do Hermes v0.23.4**, entre com a conta do proprietário e abra **Capabilities → Plugins** no perfil do gateway. Para uma instalação nova, use **Install from Git** com o repositório `NeritonDias/hermes-ryzeapi`. Se o pacote já estiver instalado, abra **RyzeAPI** nessa lista. Habilite **Agent** para carregar as ferramentas e **Desktop** para mostrar **RyzeAPI** no menu lateral. A escolha de Desktop fica salva neste navegador.

Execute o comando de configuração abaixo no contêiner com `--lifecycle coolify --listener-host 0.0.0.0 --owner-subject "$OIDC_SUB" --owner-issuer "$OIDC_ISS"`. Use o ID exato do proprietário identificado pelo Hermes e o emissor OIDC verificado. A API administrativa recusa outras identidades. A porta 9131 fica na rede privada do proxy, sem publicação no host. Configure uma única rota Traefik para o hostname dedicado, caminho exato `/ryzeapi/events` e método POST, apontando para este gateway na porta 9131. O Webapp continua na porta interna 9120. Consulte o [modelo da rota](traefik.example.yaml). Para migrar uma configuração existente que usa 9120, execute novamente o configurador.

Após ativar ou alterar permissões, faça o redeploy apenas deste gateway quando solicitado. Atualize a tela para confirmar a saúde do receptor. Pausar revoga as permissões locais imediatamente e desativa o webhook próprio no provedor. Use **Reconciliar e pausar** se a resposta remota for incerta. Use instância, label e perfil dedicados. Coloque os arquivos aprovados em `$HERMES_HOME/workspace/attachments/` e informe um caminho relativo a esse diretório.

Em **Configurações**, marque as permissões do contato, confirme e clique em **Salvar firewall**. Para cada grupo, escolha o modo, confirme e clique em **Salvar grupo**. As permissões ficam no volume do perfil, inclusive com o canal pausado. **Ativar Hermes** é uma ação separada e exige o webhook configurado e um contato com permissão para comandar e receber.

## Configurar a publicação

Use scripts/configure.py com o Python Hermes. Ele grava somente opções não secretas em ryzeapi/deployment.json do perfil, modo 0600:

```bash
python /caminho/do/perfil/plugins/ryzeapi/scripts/configure.py \
  --public-origin https://ia.example.com \
  --webhook-url https://hooks.example.com/ryzeapi/events \
  --listener-port 9131 \
  --gateway-service hermes-gateway.service \
  --webhook-label hermes-ryzeapi \
  --check
```

Substitua os valores de exemplo; depois remova --check para gravar. Reinicie dashboard/gateway em janela ociosa para aplicar deployment.json. Somente o modo systemd usa o nome de serviço. No Webapp publicado, use as opções Coolify acima e a API de plugin padrão do Hermes em processo, que recebe a identidade OIDC verificada.

Este script não cria DNS, certificados TLS, regras de proxy nem unidades systemd.

Requisitos do proxy:

- O painel fica atrás de autenticação, por exemplo autenticação nativa Hermes ou provedor de acesso no proxy. Os cabeçalhos Origin/x-ryze-ui usados pelo plugin protegem a requisição, mas NÃO autenticam o usuário.
- Preserve o Origin público configurado e repasse o tráfego do dashboard ao seu upstream local.
- Publique exclusivamente POST /ryzeapi/events do listener loopback configurado, com HTTPS e sem remover o cabeçalho Authorization. A RyzeAPI enviará o segredo configurado pelo plugin.
- Não coloque desafio interativo de login na rota de webhook. Não exponha /health, /maintenance ou a porta inteira do listener; não exponha bancos/configurações.
- Permita saída HTTPS e WSS à RyzeAPI. O listener não deve escutar na interface pública.

Você pode usar qualquer proxy/infraestrutura que cumpra esse contrato. Oracle e Cloudflare não são dependências. Não desative a autenticação do painel para fazer o webhook funcionar.

## Conta, WhatsApp e firewall

1. Abra a aba RyzeAPI no dashboard autenticado. Informe TokenAccount para listar/criar instâncias, ou TokenInstance para uma instância existente. Segredos ficam fora do código em ryzeapi/settings.json.
2. Escolha a instância explicitamente. Nesta versão, criar está no fluxo de criação/seleção enquanto o canal está pausado; não é uma operação independente com canal ativo.
3. Gere QR/código em superfície privada e pareie o aparelho. Aguarde estado conectado, não apenas QR gerado.
4. Configure contatos autorizados. Receber permite resposta/envio; Comandar permite execução. Nenhum contato é liberado por padrão.
5. Se usar grupos, sincronize o catálogo, selecione e confirme políticas por grupo. Só ouvir é arquivo passivo; todos os membros em modo responder podem acionar ferramentas do agente — use apenas grupos confiáveis.
6. Configure buffer e eco de transcrição. Ative o canal; confira WS e webhook, saúde do consumidor e permissões.
7. Faça teste real com remetente/destino autorizados e verifique entrega e rejeição de remetentes não autorizados.

Se ferramentas não aparecerem no chat, confira o toolset ryzeapi na configuração de ferramentas daquela sessão/perfil. Skills não habilitam ferramentas ou contornam autorização.

## Validação

- Plugins list: ryzeapi carregado, sem erro.
- Nova sessão: ryzeapi e ryzeapi-painel em skills_list; referências abrindo com skill_view.
- Verificação reproduzível, com o Python Hermes: python /caminho/do/perfil/plugins/ryzeapi/scripts/verify_install.py (sem chamadas à RyzeAPI).
- Painel: estado conectado confirmado e consumidor saudável; WS conectado sozinho não basta.
- Teste dry_run de envio: valida sem POST externo.
- Teste real autorizado: aceite, ID de mensagem e recibo/renderização conforme o formato. Não reenviar automaticamente em timeout.

## Migrar do WhatsApp nativo

O plugin pode substituir o canal nativo baseado em Baileys nos fluxos suportados, sem modificar o núcleo do Hermes. Não é a integração oficial WhatsApp Business Cloud API da Meta. **Não há promessa de equivalência total nesta versão.**

| Recurso | Situação neste plugin |
| --- | --- |
| Conversas, imagens, documentos e áudio | Adaptador implementado; STT depende do Hermes e mídia tem limites próprios. |
| Grupos e controle de acesso | Políticas próprias, incluindo arquivo passivo, menções e membros autorizados. Reconfigure as permissões. |
| Envio de enquetes | Ferramenta disponível; votos de retorno e esclarecimentos automáticos em enquete não têm paridade completa. |
| Respostas com anexos citados | Recuperação completa desses arquivos não está validada. |
| Streaming por edição, confirmação de leitura e modo self-chat | Não declarados equivalentes nesta versão; valide os fluxos necessários antes de migrar. |
| Sessões, permissões e destinos de cron existentes | Não são migrados automaticamente de `whatsapp` para `ryzeapi`. |

A comparação usa a [documentação oficial do canal nativo](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp), consultada em 15/09/2026, e o código desta release. O Hermes evolui; confira novamente ao atualizar.

1. Faça backup privado das configurações e preserve as credenciais da sessão nativa. Não compartilhe esse backup.
2. Configure RyzeAPI e firewall com o canal pausado. A sessão nativa não é importada; pareie pela RyzeAPI.
3. Em janela ociosa, desabilite o canal WhatsApp nativo na configuração do gateway. Se ativado por `.env`, use `WHATSAPP_ENABLED=false`; confira também overrides no perfil. Não desative Telegram ou outros canais.
4. Ative RyzeAPI e reinicie os processos necessários. Evite dois adaptadores respondendo pela mesma conta.
5. Revise destinos de cron/home channel e permissões explicitamente para `ryzeapi`. Teste DM, grupos, anexos, voz e tarefas agendadas que você realmente usa.
6. Se precisar voltar, pause/desabilite o canal RyzeAPI antes de reativar o nativo. Não restaure SQLite antigo sobre filas novas nem repita envios cujo resultado seja incerto.

## Solução de problemas

| Sintoma | Verifique |
| --- | --- |
| Aba ou ferramentas ausentes | Mesmo usuário/perfil, plugin habilitado, dependências, Doctor e reinício do dashboard/gateway. |
| Skills ausentes | Carregamento do plugin, sessão nova e avisos de conflito; execute `scripts/verify_install.py`. |
| Conectado, mas sem resposta | Consumidor, instância selecionada, firewall e regra de menção do grupo; WebSocket conectado não comprova processamento. |
| Webhook sem eventos | Rota HTTPS exata, repasse de Authorization e ausência de login interativo apenas nessa rota. |
| QR expirado | Gere outro QR em superfície privada; nunca publique um screenshot. |
| Envio aceito sem mensagem visível | Consulte ID/recibos e limites do formato. Não reenvie automaticamente após timeout. |

Compartilhe apenas logs sanitizados em issues. Não publique `settings.json`, QR, tokens, bancos nem conversas.

## Atualização e remoção

Faça backup privado de configuração e dados antes de atualizar. Pause o canal e espere tarefas em andamento terminarem; pausa não desfaz tarefas já aceitas. Não copie um banco antigo por cima do atual em rollback.

Atualizações nativas:

```bash
hermes plugins update ryzeapi
# Somente para dependências gerenciadas manualmente em ambiente personalizado
# python -m pip install -r /caminho/do/perfil/plugins/ryzeapi/requirements.txt
hermes plugins doctor /caminho/do/perfil/plugins/ryzeapi --ci
```

Reinicie os processos que carregam o plugin em janela ociosa; confira as skills em sessão nova. Para instalar por revisão imutável, o instalador aceita --ref com SHA completo de 40 caracteres; use o SHA associado à release, não uma tag como se fosse SHA.

O instalador de skills salva hashes de propriedade em ryzeapi/skill-install.json. Atualiza cópias inalteradas e guarda a versão anterior em ryzeapi/skill-backups/. Alterações locais e arquivos extras geram conflito: são preservados. Revise/guarde suas personalizações antes de retirar a cópia conflitante; ao recarregar, o plugin poderá instalar a versão empacotada. As versões qualificadas continuam acessíveis sem substituir sua edição.

Desabilite o plugin antes de remover:

```bash
hermes plugins disable ryzeapi
hermes plugins uninstall ryzeapi
```

Confirme as opções mostradas pela sua versão Hermes. O plugin não apaga sua conta RyzeAPI, aparelho, dados ou cópias das skills ao ser desabilitado/removido. Remova ryzeapi e ryzeapi-painel pelo gerenciador de skills se desejar; preserve antes suas personalizações. Arquivos privados de conversas/SQLite precisam de política de retenção própria.
