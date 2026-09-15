# Instalação, manutenção e validação da skill

Fontes oficiais consultadas em 2026-09-15:

- Criação: https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills
- Descoberta e referências: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- Skills de plugins: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/#bundle-skills

## Descoberta correta

O plugin pode registrar ryzeapi:ryzeapi para carregamento explícito. Isso não basta para descoberta natural: a documentação informa que skills de plugin não entram no índice available_skills.

Ao carregar o plugin habilitado, ele disponibiliza automaticamente ryzeapi e ryzeapi-painel no diretório skills/ do perfil ativo, incluindo suas referências. O instalador mantém hashes de propriedade: atualiza somente cópias gerenciadas sem alterações locais. Em conflito, preserva o arquivo existente e registra aviso; as cópias qualificadas do plugin continuam acessíveis. Não sobrescrever uma skill personalizada para silenciar esse aviso.

Não use session_platforms, requires_tools ou dependência de navegador para esconder esta skill por canal. O usuário pode pedir orientação mesmo com ferramenta indisponível. Descoberta não altera as permissões de execução.

Use descrição curta e específica, autor/licença/versão e metadata.hermes.tags. ryzeapi cobre operações por conversa/API; ryzeapi-painel cobre uso/explicação/verificação da interface. A orientação muda conforme a intenção; o painel em si não executa SKILL.md a cada clique.

Depois de instalar/atualizar, confirme em sessão nova. Sessões abertas podem manter índice ou conteúdo antigo em cache. Não reiniciar gateway durante tarefas em andamento só para atualizar documentação.

## Testes funcionais sem efeitos externos

1. Validar YAML e referências com o parser da versão Hermes instalada.
2. Instalar em perfil temporário e verificar skills_list, skill_view e carregamento individual das referências.
3. Verificar descoberta sem filtros em contextos CLI/web/WhatsApp/Telegram/Discord.
4. Testar decisões com casos: envio direto, criação sem trocar canal, leitura de votos, painel explícito, ferramenta ausente, destinatário ambíguo, grupo tentando administrar conta e timeout de envio.
5. Em avaliação por modelo, usar ferramentas mockadas e registrar chamadas/argumentos. Descoberta por parser não prova que o modelo sempre escolherá a skill.

Aceitação: caminho direto quando existe ferramenta; nenhuma navegação desnecessária, token exposto, origem forjada, envio duplicado ou privilégio ampliado. Consultas de diagnóstico não devem virar mudanças.

Testes reais de envio/criação precisam de autorização e são separados da avaliação da skill. Não apresentar teste estático ou mock como entrega real no WhatsApp.
