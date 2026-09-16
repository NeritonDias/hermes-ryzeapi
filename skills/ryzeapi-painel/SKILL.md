---
name: ryzeapi-painel
description: "Configurar e verificar o painel WhatsApp da RyzeAPI."
version: 0.14.0-beta.1
author: Neriton Dias
license: MIT
metadata:
  hermes:
    tags: [ryzeapi, painel, configuracao, interface, firewall]
    category: integrations
---

# Painel RyzeAPI no Hermes

Orientar e operar a interface instalada do plugin, com verificação de persistência e preservação das permissões. Autor: Neriton Dias · Instagram [@neritondias](https://www.instagram.com/neritondias/).

## When to Use

- Pedidos para usar, explicar ou verificar o painel RyzeAPI: conta, QR, instâncias, métricas, buffer, transcrição e firewall.
- Diagnóstico de formulários, salvamento e estado exibido, inclusive quando solicitado por WhatsApp, Telegram ou outro chat.
- Não usar apenas porque a conversa acontece no chat web. Pedidos de enviar mensagens ou operar a API diretamente pertencem à skill ryzeapi.

## Prerequisites

Plugin e dashboard habilitados no perfil correto. Para operar visualmente, use a ferramenta de navegador disponível no Hermes e uma sessão autenticada pelo usuário. Para apenas explicar um fluxo, não é necessário abrir navegador.

Não peça credenciais em grupos. Reutilize sessão legítima quando possível; solicite a etapa humana somente se realmente necessária para acessar o painel solicitado.

## Quick Reference

| Área | Finalidade |
| --- | --- |
| Conta pessoal | Configurar credencial com entrada protegida; nunca copiar token à conversa. |
| Visão geral | Estado do canal, conexão e ações relevantes. |
| Instâncias | Consultar instâncias e vínculo. Inspecionar não é selecionar para o Hermes. |
| Métricas | Saúde, fila, tempos e entregas observadas. Sem amostra não significa zero. |
| Configurações | Buffer, eco de transcrição e firewall de contatos/grupos. |

## Procedure

1. Identifique a intenção, instância/grupo e alterações autorizadas. Um pedido para explicar ou diagnosticar não autoriza salvar mudanças.
2. Se operar a tela, confira os controles reais. Não invente um botão cuja presença varie por versão.
3. Execute apenas a mudança pedida, conforme os contratos abaixo.
4. Confira retorno de salvamento, releia o estado e, quando pertinente, atualize a página. Considere concluído somente se o valor persistir para o alvo correto.
5. Informe o resultado observado, sem token/QR/dados privados. Se a consulta falhar, preserve a configuração e reporte o erro.

## Contratos dos controles

- Instâncias: criar, selecionar para o Hermes, gerar QR e conectar são ações distintas. Preserve o canal ativo ao consultar outra instância. Uma UI que só permite criação durante seleção tem limitação de interface, não uma exigência da API.
- Pareamento: gerar QR/código somente quando solicitado, em superfície privada. “Conectado” exige confirmação do aparelho. Não publicar QR em grupo.
- Contatos: Receber permite destino; Comandar permite execução. Não liberar comandos para cadastrar apenas um destinatário.
- Grupos: sincronizar atualiza catálogo de ID/nome sem autorizar. Buscar, selecionar, editar, salvar e reler. Remover da seleção não é excluir o grupo do WhatsApp.
- Políticas: bloqueado / só ouvir / ouvir e responder. Em responder, escolher menções/respostas ou todas as mensagens; autores autorizados ou todos os membros. Confirmar qualquer ampliação para o grupo exato.
- Só ouvir arquiva atividade permitida sem acionar IA/STT/eco. Sincronizar não importa histórico nem cria pastas de conversa sem atividade.
- Buffer: intervalo de silêncio para reunir mensagens; preserve limites e valor da instalação.
- Transcrição: eco desmarcado impede cópia automática à conversa, não a transcrição interna. Não alterar provedor STT.

## Pitfalls

- Falha de consulta não autoriza limpar configurações, refazer cadastro ou desativar autenticação.
- Não editar banco/configuração com terminal para contornar erro visual ou permissão.
- Não exigir login no painel para tarefa direta já atendida por ferramenta RyzeAPI.
- Perfil/canal de origem não confere administração; use a sessão autenticada e a autorização real.
- Métricas sem amostra não são zero; WebSocket conectado não prova resposta do agente.

## Verification

Mensagem de sucesso e valor exibido no formulário não bastam: confira persistência após releitura no mesmo grupo/instância. Pareamento precisa de estado conectado confirmado. Envio aceito pela API não prova entrega/renderização.

Esta skill e ryzeapi são disponibilizadas juntas pelo plugin. O Hermes escolhe qual carregar conforme a tarefa, sem carregar ambos os textos em toda conversa. Para operações diretas ou diagnóstico do processamento, carregue ryzeapi; isso não autoriza nenhuma mudança adicional.
