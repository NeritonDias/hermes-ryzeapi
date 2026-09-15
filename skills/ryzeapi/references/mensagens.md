# Mensagens nativas

Descubra a ferramenta e siga seu schema instalado. Cada envio recebe payload e request_id; para chat, number é o destino. Só omita number para o chat RyzeAPI atual, nunca para Telegram/Discord. dry_run valida sem envio externo.

| Ferramenta | Campos e cuidados |
| --- | --- |
| ryzeapi_send_text | message; replyTo/menções conforme schema e referências conhecidas. |
| ryzeapi_send_media | mediaType image/video/audio/document; mediaUrl ou mediaBase64. message é legenda; isVoice distingue PTT de áudio regular. |
| ryzeapi_send_sticker | imageUrl ou file_path escolhido pelo usuário. |
| ryzeapi_send_contact | vcard com fullName/phone e opcionais organization/email/url. Somente dados autorizados. |
| ryzeapi_send_location | latitude/longitude e name/address conforme schema. Localização estática. |
| ryzeapi_send_pix | merchantName, pixKey, pixKeyType CPF/CNPJ/EMAIL/PHONE/RANDOM. Não paga nem confirma pagamento. |
| ryzeapi_send_buttons | contentText e 1–3 buttons com id/displayText/type: REPLY, URL, CALL ou COPY. |
| ryzeapi_send_list | contentText, buttonText, sections com rows id/title/description. Até 10 seções × 10 linhas. |
| ryzeapi_send_carousel | cards com header, body e buttons opcionais. Até 10 cards; validar renderização no cliente. |
| ryzeapi_send_form | message, formType, buttonLabel e campos expostos. Native Flow orientado a apps móveis. |
| ryzeapi_send_poll | question, 2–12 options e maxAnswer opcional. Votos são outra operação. |
| ryzeapi_send_event | name, startAt/endAt ISO8601 com fuso. Não inventar presença confirmada. |
| ryzeapi_send_reaction | messageId do destino correto, reaction, fromMe; participant quando exigido para grupo. |
| ryzeapi_send_status | Publicação na audiência WhatsApp, não resposta privada. Exige aprovação de conteúdo/audiência e confirm_status_broadcast. |

## Botões e retornos

REPLY usa id lógico e displayText. COPY usa em id o texto exato a copiar; URL usa URL HTTPS; CALL usa telefone internacional. Evite misturar REPLY com URL/CALL/COPY para compatibilidade Desktop. COPY não implica retorno à IA.

O plugin correlaciona escolhas de botões/listas com menus aceitos pela API usando IDs de transporte próprios, instância, chat e prazo. A escolha não concede autorização extra. Menus antigos sem rastreamento ou expirados não são citações válidas; não repetir uma tarefa concluída por outro clique.

Carrossel: usar mídia válida quando o objetivo for testar renderização; não reenviar automaticamente se o cliente não mostrar. Retorno de formulários, votos e presença requer consulta/validação própria, não inferência a partir do envio.

## Segurança e confirmação

- Preserve request_id e payload para consultar a mesma operação; resultado incerto não autoriza novo ID.
- Não invente chave PIX, contato, referência de mensagem ou localização pessoal.
- file_path deve ser anexo escolhido pelo usuário; limite atual de 8 MiB. Não enviar credenciais/configuração. Não prometer áudios ilimitados.
- Grupos enviam somente ao próprio grupo autorizado. Status é proibido a partir de grupos e não usa a audiência do firewall de destinatários.
- Telefone/LID exige identidade verificada, não adivinhação.
- Informe “aceito pela API” se esse for o único estado conhecido; não afirmar entregue, lido ou renderizado.

Documentação: https://docs.ryzeapi.cloud/pt/api/messages/overview . Campos executáveis são os do schema instalado, mesmo quando a API tiver opções adicionais.
