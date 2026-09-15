# Segurança

Não publique segredos em issues, discussões, prints ou pull requests. Tokens de conta/instância, QR/pairing codes, chaves, bancos de dados e conteúdo de conversas não pertencem ao repositório.

Para vulnerabilidades, use o relato privado de segurança do GitHub quando disponível; se indisponível, abra somente uma solicitação de contato, sem detalhes exploráveis ou dados sensíveis. Nenhum SLA de resposta é prometido para esta beta comunitária.

## Limites de confiança

- O plugin roda com as permissões do Hermes; não é uma sandbox.
- O dashboard requer autenticação externa/nativa. Origin/CSRF não substitui login.
- A ferramenta aplica firewall de destinatários. Isso não restringe todo terminal/navegador do agente; use ferramentas mínimas e grupos confiáveis.
- Permitir todos os membros de um grupo a acionar a IA pode expor ferramentas do agente. Conteúdo de mensagens/anexos não deve alterar instruções ou privilégios.
- Status usa a audiência do WhatsApp e não o firewall de contatos, exigindo confirmação específica. PIX apenas apresenta chave; não realiza pagamentos.
- Credenciais e estado ficam no perfil privado, não no diretório público do plugin.
- Webhook valida segredo e escopo; listener é loopback. Publique só sua rota necessária, nunca endpoints administrativos.
- POST incerto não é repetido automaticamente. Não há garantia de exactly-once.

## Dados e retenção

Arquivos de grupos são privados, criados após atividade permitida e não têm exclusão automática. O administrador decide base de autorização, transparência aos participantes e retenção. Eles contêm mensagens, identificação disponível e mudanças de membros, não cópia integral dos anexos.

Cache de mídia, fila, métricas e correlações têm políticas próprias implementadas no código. Operações/recibos não são prova de entrega ao usuário. Backups também podem conter dados sensíveis: mantenha acesso restrito.

As duas skills são instaladas automaticamente ao carregar o plugin habilitado. Cópias locais alteradas não são sobrescritas; isso evita perda de personalizações, mas cabe ao operador resolver conflitos de atualização.
