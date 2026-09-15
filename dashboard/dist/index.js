/* Native Hermes dashboard extension. React and authentication come from the host. */
(() => {
  'use strict';
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React } = SDK;
  const { useState, useEffect, useRef } = React;
  const h = React.createElement;
  const { Button, Input, Label } = SDK.components;
  const api = (path, data) => SDK.fetchJSON('/api/plugins/ryzeapi' + path, data === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ryze-UI': '1' }, body: JSON.stringify(data)
  });
  const states = { connected: 'Conectado', connecting: 'Conectando', disconnected: 'Desconectado', loggedout: 'Desconectado', unknown: 'Não confirmado', qr: 'Aguardando leitura' };
  const channelStates = { ...states, logged_out: 'Sessão encerrada', qr_ready: 'Aguardando QR', pair_success: 'Pareado; aguardando conexão', temp_banned: 'Restrição temporária', keepalive_timeout: 'Conexão instável', keepalive_restored: 'Conexão restabelecida' };
  const dateText = seconds => seconds ? new Date(seconds * 1000).toLocaleString('pt-BR') : 'Sem registro';
  const timingStages = [['buffer','Espera do buffer'],['identity','Identificação do contato'],
    ['media_download','Download de anexos'],['stt_queue','Fila de transcrição'],['stt_execution','Transcrição do áudio'],
    ['preparation','Preparação do lote'],['gateway_handoff','Encaminhamento ao Hermes'],
    ['agent_to_first_send','Até a primeira resposta'],['send_text','Envio de texto'],['send_media','Envio de anexo']];
  const durationText = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ?
    (value < 1000 ? value.toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' ms' :
      (value / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' s') : 'Sem medição';
  const tabs = ['Visão geral', 'Instâncias', 'Métricas', 'Configurações'];
  const icon = name => h('svg', { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true },
    ...(name === 'check' ? [h('circle', { key: 'c', cx: 12, cy: 12, r: 10 }), h('path', { key: 'p', d: 'm7 12 3 3 7-7' })] :
      name === 'user' ? [h('circle', { key: 'c', cx: 12, cy: 7, r: 3 }), h('path', { key: 'p', d: 'M5 21v-3a7 7 0 0 1 14 0v3' })] :
      name === 'refresh' ? [h('path', { key: 'p', d: 'M20 7v5h-5M4 17v-5h5M5 7a8 8 0 0 1 14-1l1 6M4 12l1 6a8 8 0 0 0 14-1' })] :
      name === 'arrow' ? [h('path', { key: 'p', d: 'M4 12h16m-5-5 5 5-5 5' })] :
      name === 'settings' ? [h('circle', { key: 'c', cx: 12, cy: 12, r: 3 }), h('path', { key: 'p', d: 'M9.5 3h5l.5 2.2 1.5.9 2.2-.7 2.5 4.3-1.7 1.5v1.6l1.7 1.5-2.5 4.3-2.2-.7-1.5.9-.5 2.2h-5L9 18.8l-1.5-.9-2.2.7-2.5-4.3 1.7-1.5v-1.6L2.8 9.7l2.5-4.3 2.2.7L9 5.2Z' })] :
      [h('circle', { key: 'c', cx: 12, cy: 12, r: 10 }), h('path', { key: 'p', d: 'M12 11v6m0-10h.01' })]));
  function TimingDetails({ timings }) {
    const rows = timingStages.filter(([key]) => Number.isInteger(timings?.[key]?.window_samples) && timings[key].window_samples > 0);
    return h('section', { className: 'ryze-details ryze-timings', 'aria-label': 'Tempo por etapa' }, h('h3', null, 'Tempo por etapa'),
      h('p', { className: 'ryze-help' }, 'Últimas 256 amostras por etapa, desde o reinício do serviço. P95: 95% das medições ficaram nesse tempo ou abaixo. Etapas podem se sobrepor; não some os tempos.'),
      rows.length ? h('ul', { className: 'ryze-timing-list' }, ...rows.map(([key, label]) => {
        const sample = timings[key];
        return h('li', { key }, h('h4', null, label), h('dl', null,
          ...[['Última',durationText(sample.last_ms)],['Média',durationText(sample.mean_ms)],
            ['P95',durationText(sample.p95_ms)],['Amostras',String(sample.window_samples)]].map(([name,value]) =>
            h('div', { key: name }, h('dt', null, name), h('dd', null, value)))));
      })) : h('p', null, 'Ainda sem medições. Os tempos aparecem conforme as mensagens passam por cada etapa.'),
      h('p', { className: 'ryze-help' }, '“Até a primeira resposta” inclui a fila do Hermes, o modelo e as ferramentas até a primeira tentativa de envio. Não confirma entrega no WhatsApp.'));
  }
  function errorText(error) {
    // Hermes 0.21.3 keeps structured errors in .body; earlier SDKs used .message.
    const message = String(error?.body || error?.message || '');
    const start = message.indexOf('{');
    if (start >= 0) {
      try { const detail = JSON.parse(message.slice(start)).detail; if (typeof detail === 'string') return detail; } catch (_) { /* Not a JSON error. */ }
    }
    if (error?.status === 502) return 'O serviço não respondeu corretamente pelo proxy. Atualize a conexão antes de gerar outro código.';
    if (error?.status === 504) return 'A solicitação demorou demais. Atualize o estado antes de tentar novamente.';
    return 'Não foi possível confirmar a operação. Atualize o estado antes de tentar novamente.';
  }
  const numbers = value => [...new Set(String(value || '').split(/[\s,;]+/).filter(Boolean))];
  function Contacts({ owners, recipients, onChange, disabled }) {
    const [number, setNumber] = useState(''), [message, setMessage] = useState('');
    const command = numbers(owners), receive = numbers(recipients), all = [...new Set([...command, ...receive])];
    function update(n, type, checked) {
      let a = command, b = receive;
      if (type === 'command') { a = checked ? [...a, n] : a.filter(v => v !== n); if (checked && !b.includes(n)) b = [...b, n]; }
      else { b = checked ? [...b, n] : b.filter(v => v !== n); if (!checked) a = a.filter(v => v !== n); }
      onChange([...new Set(a)].join(','), [...new Set(b)].join(','));
    }
    return h('div', { className: 'ryze-contacts' },
      h('p', { className: 'ryze-help' }, 'Quem comanda também precisa receber respostas. Marcar “Comandar” inclui “Receber”; retirar “Receber” também retira o comando. Revise e confirme antes de salvar. Números brasileiros são reconhecidos com ou sem o nono dígito.'),
      all.length ? h('ul', null, ...all.map(n => h('li', { key: n }, h('strong', null, '+' + n),
        h('label', null, h('input', { type: 'checkbox', checked: receive.includes(n), disabled, onChange: e => update(n, 'receive', e.target.checked), 'aria-label': 'Receber mensagens: ' + n }), 'Receber'),
        h('label', null, h('input', { type: 'checkbox', checked: command.includes(n), disabled, onChange: e => update(n, 'command', e.target.checked), 'aria-label': 'Comandar Hermes: ' + n }), 'Comandar'),
        h('button', { type: 'button', className: 'ryze-link', disabled, 'aria-label': 'Remover contato ' + n,
          onClick: () => { onChange(command.filter(v => v !== n).join(','), receive.filter(v => v !== n).join(',')); setMessage('Contato removido da edição. Salve o firewall para aplicar.'); } }, 'Remover')))) : h('p', null, 'Nenhum contato autorizado. Adicione seu número pessoal.'),
      h('div', { className: 'ryze-contact-add' }, h('div', null, h(Label, { htmlFor: 'ryze-contact-number' }, 'Número do contato'),
        h(Input, { id: 'ryze-contact-number', value: number, type: 'tel', inputMode: 'tel', maxLength: 24, disabled, placeholder: '55 + DDD + número',
          onChange: e => setNumber(e.target.value), onKeyDown: e => { if (e.key === 'Enter') e.preventDefault(); }, 'aria-describedby': 'ryze-contact-help' })),
        h(Button, { type: 'button', outlined: true, disabled: disabled || !/^\d{10,15}$/.test(number.replace(/\D/g, '')),
          onClick: () => { const n = number.replace(/\D/g, ''); if (!all.includes(n)) onChange(owners, [...receive, n].join(',')); setNumber(''); setMessage('Contato adicionado para receber. Marque Comandar somente se confiar nele para executar tarefas. Salve para aplicar.'); document.getElementById('ryze-contact-number')?.focus(); } }, 'Adicionar contato')),
      h('p', { id: 'ryze-contact-help', className: 'ryze-help' }, 'DDI + DDD + número. Não libera grupos nem contatos fora desta lista.'),
      message && h('p', { role: 'status', className: 'ryze-help' }, message));
  }
  function Groups({ instance, drafts, setDrafts, picked, setPicked, disabled }) {
    const [rows, setRows] = useState(null), [search, setSearch] = useState('');
    const [open, setOpen] = useState(false), [cursor, setCursor] = useState(-1), [activeGroup, setActiveGroup] = useState('');
    const [removing, setRemoving] = useState('');
    const picker = useRef(null);
    const [busy, setBusy] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState('');
    const mounted = useRef(true), locked = useRef(false);
    useEffect(() => { mounted.current = true; load(); return () => { mounted.current = false; }; }, [instance]);
    async function load() {
      try { const data = await api('/groups'); if (mounted.current && data.instance === instance) setRows(data.groups); }
      catch (e) { if (mounted.current) setError(errorText(e)); }
    }
    async function action(label, path, data) {
      if (locked.current) return;
      locked.current = true; setBusy(label); setError(''); setNotice('');
      try {
        const result = await api(path, data);
        if (!mounted.current) return;
        if (result.instance !== instance) throw new Error('Instance changed');
        setRows(result.groups);
        if (data.jid) {
          setDrafts(previous => { const next = { ...previous }; delete next[instance + ':' + data.jid]; return next; });
          setActiveGroup(''); setRemoving('');
          if (data.mode === 'blocked') {
            setPicked(previous => { const next = { ...previous }; delete next[instance + ':' + data.jid]; return next; });
          }
          focusGroup(data.mode === 'blocked' ? '' : data.jid);
        }
        setNotice(data.jid ? data.mode === 'blocked' ? 'Grupo removido da seleção e bloqueado. O arquivo de conversas foi preservado.' : 'Permissões salvas. Clique no grupo para editar novamente.' : 'Grupos sincronizados. Novos grupos continuam bloqueados.');
      } catch (e) { if (mounted.current) setError(errorText(e)); }
      finally { locked.current = false; if (mounted.current) setBusy(''); }
    }
    const labels = { blocked: 'Bloqueado', listen: 'Só ouvir', respond: 'Ouvir e responder' };
    const visible = (rows || []).filter(row => (row.name + ' ' + row.jid).toLocaleLowerCase('pt-BR').includes(search.toLocaleLowerCase('pt-BR')));
    const chosen = (rows || []).filter(row => row.mode !== 'blocked' || picked[instance + ':' + row.jid] || drafts[instance + ':' + row.jid]);
    const currentGroup = !removing && chosen.find(row => row.jid === activeGroup);
    const removalGroup = chosen.find(row => row.jid === removing);
    function focusGroup(jid) {
      requestAnimationFrame(() => document.getElementById(jid ? 'ryze-group-chip-' + jid : 'ryze-group-search')?.focus());
    }
    function closeEditor() { setActiveGroup(''); focusGroup(activeGroup); }
    function choose(row) {
      if (busy || disabled) return;
      const key = instance + ':' + row.jid;
      setPicked(previous => ({ ...previous, [key]: true })); setActiveGroup(row.jid); setRemoving(''); setError('');
      if (row.mode === 'blocked' && !drafts[key] && row.present) setDrafts(previous => ({ ...previous, [key]: { ...row, mode: 'listen', confirm: false } }));
      setOpen(false); setSearch(''); setCursor(-1);
      setNotice(row.mode === 'blocked' ? 'Grupo adicionado à seleção. Configure e salve para liberar o acesso.' : 'Edite as opções deste grupo. A permissão salva vale até confirmar uma alteração.');
    }
    function remove(row) {
      if (busy || disabled) return;
      const key = instance + ':' + row.jid;
      if (row.mode === 'blocked') {
        setPicked(previous => { const next = { ...previous }; delete next[key]; return next; });
        setDrafts(previous => { const next = { ...previous }; delete next[key]; return next; });
        setNotice('Seleção removida. O grupo continua bloqueado.');
        if (activeGroup === row.jid) setActiveGroup('');
        setRemoving(''); focusGroup('');
      } else {
        setRemoving(row.jid); setNotice('');
      }
      setOpen(false); setError('');
    }
    useEffect(() => {
      if (removing) document.getElementById('ryze-group-remove-title')?.focus();
      else if (activeGroup) document.getElementById('ryze-group-editor-title')?.focus();
    }, [activeGroup, removing]);
    useEffect(() => {
      const close = e => { if (!picker.current?.contains(e.target)) setOpen(false); };
      document.addEventListener('pointerdown', close);
      return () => document.removeEventListener('pointerdown', close);
    }, []);
    useEffect(() => { if (open && cursor >= 0) document.getElementById('ryze-group-option-' + cursor)?.scrollIntoView({ block: 'nearest' }); }, [open, cursor]);
    return h('section', { className: 'ryze-firewall ryze-groups', 'aria-labelledby': 'ryze-groups-title', 'aria-busy': !!busy },
      h('div', { className: 'ryze-group-heading' }, h('div', null,
        h('h3', { id: 'ryze-groups-title' }, 'Firewall de grupos'),
        h('p', { className: 'ryze-help' }, 'Grupos da instância ', instance, '. Sincronizar não libera acesso.')),
        h(Button, { type: 'button', outlined: true, disabled: !!busy || disabled,
          onClick: () => action('Sincronizando grupos…', '/groups/sync', {}) }, busy === 'Sincronizando grupos…' ? busy : 'Listar / sincronizar grupos')),
      h('p', null, 'Só ouvir arquiva as conversas sem acionar a IA. Ouvir e responder também permite executar tarefas conforme as permissões de cada grupo.'),
      error && !removalGroup && h('div', { role: 'alert', className: 'ryze-feedback' }, error,
        h('button', { type: 'button', className: 'ryze-link', disabled: !!busy, onClick: () => { setError(''); load(); } }, 'Consultar catálogo salvo')),
      notice && h('p', { role: 'status', className: 'ryze-help' }, notice),
      rows === null ? h('p', { role: 'status' }, error ? 'Catálogo indisponível.' : 'Carregando grupos…') : !rows.length ?
        h('p', null, 'Nenhum grupo no catálogo. Conecte o WhatsApp e use Listar / sincronizar grupos.') : h(React.Fragment, null,
        h('div', { className: 'ryze-field' }, h(Label, { htmlFor: 'ryze-group-search' }, 'Buscar grupo por nome ou ID'),
          h('div', { className: 'ryze-group-picker', ref: picker, onBlur: e => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false); } },
            h('div', { className: 'ryze-group-box' },
              ...chosen.map(row => h('span', { key: row.jid, className: 'ryze-group-chip' + (currentGroup?.jid === row.jid ? ' is-current' : '') },
                h('button', { id: 'ryze-group-chip-' + row.jid, type: 'button', disabled: !!busy || disabled, 'aria-label': 'Editar grupo ' + row.name,
                  'aria-expanded': currentGroup?.jid === row.jid, 'aria-controls': currentGroup?.jid === row.jid ? 'ryze-group-editor' : undefined,
                  onClick: () => { setActiveGroup(currentGroup?.jid === row.jid ? '' : row.jid); setRemoving(''); setOpen(false); setNotice(''); setError(''); } },
                  h('span', { className: 'ryze-chip-name' }, row.name,
                    h('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, 'aria-hidden': true }, h('path', { d: 'm16 3 5 5-12 12-6 1 1-6Z M14 5l5 5' }))),
                  h('small', null, drafts[instance + ':' + row.jid] ? row.mode === 'blocked' ? 'Não salvo' : 'Alterações não salvas' : labels[row.mode])),
                h('button', { type: 'button', className: 'ryze-chip-remove', disabled: !!busy || disabled, 'aria-label': 'Remover seleção de ' + row.name, onClick: () => remove(row) },
                  h('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, 'aria-hidden': true }, h('path', { d: 'm6 6 12 12M18 6 6 18' }))))),
              h('div', { className: 'ryze-group-search-line' }, h('input', { id: 'ryze-group-search', role: 'combobox', type: 'text', autoComplete: 'off', value: search,
                'aria-expanded': open, 'aria-controls': 'ryze-group-options', 'aria-autocomplete': 'list',
                'aria-activedescendant': open && cursor >= 0 && visible[cursor] ? 'ryze-group-option-' + cursor : undefined,
                'aria-describedby': 'ryze-group-picker-help', placeholder: chosen.length ? 'Adicionar outro grupo…' : 'Buscar ou selecionar grupos…', disabled: !!busy || disabled,
                onClick: () => setOpen(true), onChange: e => { setSearch(e.target.value); setOpen(true); setCursor(-1); },
                onKeyDown: e => {
                  if (e.key === 'Escape') { setOpen(false); setCursor(-1); }
                  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setOpen(true); setCursor(old => visible.length ? Math.max(0, Math.min(visible.length - 1, old + (e.key === 'ArrowDown' ? 1 : -1))) : -1); }
                  if (e.key === 'Enter' && open && visible[cursor]) { e.preventDefault(); choose(visible[cursor]); }
                } }),
                h('button', { type: 'button', className: 'ryze-picker-toggle', disabled: !!busy || disabled, 'aria-label': open ? 'Fechar lista de grupos' : 'Abrir lista de grupos',
                  onClick: () => { setOpen(!open); setCursor(-1); document.getElementById('ryze-group-search')?.focus(); } }, icon('arrow')))),
            open && h('div', { className: 'ryze-group-dropdown' },
              h('ul', { id: 'ryze-group-options', role: 'listbox', 'aria-label': 'Grupos disponíveis', 'aria-multiselectable': true },
                ...visible.map((row, index) => h('li', { key: row.jid, id: 'ryze-group-option-' + index, role: 'option',
                  'aria-selected': chosen.some(item => item.jid === row.jid), className: cursor === index ? 'is-highlighted' : '',
                  onPointerDown: e => e.preventDefault(), onClick: () => choose(row) },
                  h('span', null, row.name), h('small', null, row.jid, chosen.some(item => item.jid === row.jid) ? ' · Selecionado' : '')))),
              !visible.length && h('p', { role: 'status' }, 'Nenhum grupo corresponde à busca.')))),
        h('p', { id: 'ryze-group-picker-help', className: 'ryze-help' }, 'Clique no nome de um grupo para editar; no X para remover e bloquear. Adicionar à seleção só libera acesso depois de salvar.'),
        h('p', { className: 'ryze-help', role: 'status' }, chosen.length, ' selecionados · ', rows.length, ' disponíveis · Última sincronização: ', dateText(Math.max(...rows.map(r => r.synced || 0)))),
        !chosen.length && h('p', null, 'Nenhum grupo selecionado. Abra a busca para escolher.'),
        removalGroup && h('section', { className: 'ryze-group-removal', 'aria-labelledby': 'ryze-group-remove-title' },
          h('h4', { id: 'ryze-group-remove-title', tabIndex: -1 }, 'Remover ', removalGroup.name, '?'),
          h('p', null, 'O Hermes deixará de ouvir e responder neste grupo. As conversas já arquivadas serão preservadas. O grupo continuará disponível na busca.'),
          drafts[instance + ':' + removalGroup.jid] && h('p', { className: 'ryze-help' }, 'As alterações não salvas deste grupo também serão descartadas ao confirmar.'),
          error && h('p', { role: 'alert', className: 'ryze-feedback' }, error),
          h('div', { className: 'ryze-actions' },
            h(Button, { type: 'button', disabled: !!busy || disabled,
              onClick: () => action('Removendo grupo…', '/groups/policy', { instance, jid: removalGroup.jid, mode: 'blocked', trigger: removalGroup.trigger, senders: removalGroup.senders, confirm: true }) }, busy === 'Removendo grupo…' ? busy : 'Remover e bloquear'),
            h('button', { type: 'button', className: 'ryze-link', disabled: !!busy || disabled,
              onClick: () => { setRemoving(''); setError(''); focusGroup(removalGroup.jid); } }, 'Cancelar remoção'))),
        h('div', { className: 'ryze-group-list' }, ...(currentGroup ? [currentGroup] : []).map(row => {
          const key = instance + ':' + row.jid, draft = drafts[key], edit = draft || row;
          const change = (field, value) => setDrafts(previous => ({ ...previous, [key]: { ...(previous[key] || row), [field]: value, confirm: false } }));
          const select = (field, label, options, inactive = false) => h('label', { className: 'ryze-group-field' }, h('span', null, label),
            h('select', { value: edit[field], disabled: !!busy || disabled || inactive, 'aria-label': label + ': ' + row.name,
              onChange: e => change(field, e.target.value) }, ...options.map(([value, text]) => h('option', { key: value, value }, text))));
          return h('article', { id: 'ryze-group-editor', key: row.jid, className: 'ryze-group-row', 'aria-label': row.name },
            h('div', { className: 'ryze-group-editor-heading' },
              h('div', { className: 'ryze-group-identity' }, h('h4', { id: 'ryze-group-editor-title', tabIndex: -1 }, 'Editar ', row.name), h('p', { className: 'ryze-help' }, row.jid),
                h('p', null, 'Salvo: ', labels[row.mode], !row.present ? ' · Não encontrado na última sincronização' : row.members == null ? '' : ' · ' + row.members + ' membros')),
              h('button', { type: 'button', className: 'ryze-link', disabled: !!busy || disabled, onClick: closeEditor }, 'Fechar edição')),
            h('div', { className: 'ryze-group-controls' },
              select('mode', 'Modo do grupo', [['blocked','Bloqueado'],['listen','Só ouvir'],['respond','Ouvir e responder']], !row.present),
              edit.mode === 'respond' && select('trigger', 'Quando responder', [['mentions','Menções ou respostas ao Hermes'],['all','Todas as mensagens']]),
              edit.mode === 'respond' && select('senders', 'Quem pode acionar a IA', [['authorized','Somente contatos autorizados'],['all','Todos os membros do grupo']])),
            edit.mode === 'respond' && edit.senders === 'all' && h('p', { className: 'ryze-help' }, 'Atenção: qualquer membro deste grupo poderá pedir tarefas usando as ferramentas do Hermes. Libere apenas grupos de confiança. Isso não libera mensagens privadas.'),
            draft && h('div', { className: 'ryze-group-save' }, h('p', { className: 'ryze-help' }, 'Alterações ainda não salvas.'),
              h('label', null, h('input', { type: 'checkbox', checked: !!edit.confirm, disabled: !!busy || disabled,
                onChange: e => setDrafts(previous => ({ ...previous, [key]: { ...edit, confirm: e.target.checked } })) }), ' Confirmo as permissões de ', row.name, '.'),
              h('div', { className: 'ryze-actions' }, h(Button, { type: 'button', disabled: !!busy || disabled || !edit.confirm,
                onClick: () => action('Salvando grupo…', '/groups/policy', { instance, jid: row.jid, mode: edit.mode, trigger: edit.trigger, senders: edit.senders, confirm: true }) }, busy === 'Salvando grupo…' ? busy : 'Salvar grupo'),
                h('button', { type: 'button', className: 'ryze-link', disabled: !!busy, onClick: () => { setDrafts(previous => { const next = { ...previous }; delete next[key]; return next; }); setNotice('Alterações descartadas. A permissão salva foi mantida.'); } }, 'Descartar alterações'))));
        }))),
      h('p', { className: 'ryze-help' }, 'Arquivo na VPS: grupo / data (horário de Brasília), com ID, número e nome do autor quando disponíveis. A pasta só nasce com atividade em um grupo liberado. Entradas e saídas também são registradas. Sincronizar não importa histórico. Anexos são identificados no registro; este arquivo não é uma cópia dos arquivos de mídia.'));
  }
  function App() {
    const [state, setState] = useState(null), [step, setStep] = useState(0);
    const [tab, setTab] = useState(0), [inspected, setInspected] = useState('');
    const [updatedAt, setUpdatedAt] = useState(null);
    const hydrated = useRef(false), viewTitle = useRef(null), focusView = useRef(false);
    const [busy, setBusy] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState('');
    const [feedbackScope, setFeedbackScope] = useState('global');
    const [token, setToken] = useState(''), [kind, setKind] = useState('account');
    const [items, setItems] = useState([]), [choice, setChoice] = useState(''), [name, setName] = useState('');
    const [listLoaded, setListLoaded] = useState(false);
    const [createOK, setCreateOK] = useState(false), [permit, setPermit] = useState(false), [forgetOK, setForgetOK] = useState(false);
    const [connection, setConnection] = useState(null), [number, setNumber] = useState(''), [owners, setOwners] = useState('');
    const [recipients, setRecipients] = useState('');
    const [groupDrafts, setGroupDrafts] = useState({});
    const [pickedGroups, setPickedGroups] = useState({});
    const [buffer, setBuffer] = useState('10');
    const [echoTranscripts, setEchoTranscripts] = useState(true);
    const [transport, setTransport] = useState(null), [transportError, setTransportError] = useState(false);
    const transportRequest = useRef(0);
    async function refreshDiagnostics() {
      const request = ++transportRequest.current;
      try {
        const result = await api('/transport');
        if (!alive.current || request !== transportRequest.current) return;
        if (typeof result.consumer_healthy !== 'boolean') throw new Error('Unknown diagnostic state');
        setTransport(result); setTransportError(false); setUpdatedAt(Date.now());
      } catch (_) {
        if (!alive.current || request !== transportRequest.current) return;
        setTransport(null); setTransportError(true);
      }
    }
    const [code, setCode] = useState(null), [now, setNow] = useState(Date.now());
    const [pollMessage, setPollMessage] = useState('Verificação automática a cada 5 segundos.');
    const lock = useRef(false), alive = useRef(true), feedback = useRef(null);
    const connected = connection?.status === 'connected';
    const active = state?.enabled && state?.webhook_configured && transport?.running && transport?.consumer_healthy && !transport?.maintenance_active && transport?.whatsapp_state === 'connected';
    async function refresh() {
      const next = await api('/state');
      if (alive.current) {
        setState(next);
        if (!hydrated.current) {
          hydrated.current = true;
          setOwners(next.allowed_users || ''); setKind(next.credential_kind || 'account');
          setRecipients(next.allowed_recipients || next.allowed_users || '');
          setBuffer(String(next.buffer_seconds ?? 10)); setEchoTranscripts(next.echo_transcripts ?? true);
          setStep(next.instance ? 2 : next.credential_saved ? 1 : 0);
        }
      }
      return next;
    }
    async function checkConnection() {
      const result = await api('/connection');
      if (alive.current) {
        setConnection(result.instance);
        if (result.instance.status === 'connected') setCode(null);
      }
      return result.instance;
    }
    async function run(label, action) {
      if (lock.current) return;
      setFeedbackScope(/buffer/i.test(label) ? 'buffer' : /transcri/i.test(label) ? 'transcription' : /firewall/i.test(label) ? 'firewall' : 'global');
      lock.current = true; setBusy(label); setError(''); setNotice('');
      try { await action(); }
      catch (e) { if (alive.current) setError(errorText(e)); await refresh().catch(() => {}); }
      finally { lock.current = false; if (alive.current) setBusy(''); }
    }
    useEffect(() => {
      alive.current = true;
      run('Carregando configuração…', async () => {
        const next = await refresh();
        if (next.instance) await checkConnection();
      });
      return () => { alive.current = false; };
    }, []);
    useEffect(() => { if (error) feedback.current?.focus(); }, [error]);
    useEffect(() => {
      setTransport(null); setTransportError(false);
      if (!state?.enabled) return;
      let disposed = false, timer;
      async function tick() {
        if (disposed) return;
        if (!document.hidden && !lock.current) {
          await refreshDiagnostics();
        }
        if (!disposed) timer = setTimeout(tick, 5000);
      }
      tick();
      return () => { disposed = true; clearTimeout(timer); transportRequest.current += 1; };
    }, [state?.enabled, state?.instance]);
    useEffect(() => {
      if (!state?.credential_saved) return;
      let disposed = false;
      api('/instances').then(result => { if (!disposed) { setItems(result.instances); setListLoaded(true); } }).catch(() => {});
      return () => { disposed = true; };
    }, [state?.credential_saved, state?.instance]);
    useEffect(() => { if (focusView.current) { focusView.current = false; viewTitle.current?.focus(); } }, [tab, step, inspected]);
    useEffect(() => {
      const handler = e => { if (Object.keys(groupDrafts).length || state && (buffer !== String(state.buffer_seconds ?? 10) || echoTranscripts !== (state.echo_transcripts ?? true) || owners !== (state.allowed_users || '') || recipients !== (state.allowed_recipients || ''))) { e.preventDefault(); e.returnValue = ''; } };
      window.addEventListener('beforeunload', handler);
      return () => window.removeEventListener('beforeunload', handler);
    }, [state, buffer, echoTranscripts, owners, recipients, groupDrafts]);
    useEffect(() => {
      if (!code) return;
      const timer = setInterval(() => setNow(Date.now()), 1000);
      return () => clearInterval(timer);
    }, [code]);
    useEffect(() => {
      if (!state?.instance || tab !== 1 || step !== 2) return;
      let disposed = false, timer, failures = 0;
      const instance = state.instance;
      async function tick() {
        if (disposed) return;
        let delay = 5000;
        if (!document.hidden && !lock.current) {
          try {
            const result = await api('/connection');
            if (disposed || result.instance.name !== instance) return;
            failures = 0; setConnection(result.instance);
            setPollMessage('Verificação automática a cada 5 segundos.');
            if (result.instance.status === 'connected') setCode(null);
          } catch (_) {
            if (disposed) return;
            failures += 1; delay = Math.min(30000, 5000 * 2 ** Math.min(failures, 3));
            setPollMessage('Sem resposta da RyzeAPI. Nova tentativa em ' + delay / 1000 + ' segundos.');
          }
        }
        if (!disposed) timer = setTimeout(tick, delay);
      }
      timer = setTimeout(tick, 5000);
      return () => { disposed = true; clearTimeout(timer); };
    }, [state?.instance, step, tab]);
    const remaining = code ? Math.max(0, Math.ceil((code.expiresAt - now) / 1000)) : 0;
    const field = (id, title, value, setter, props = {}, help) => h('div', { className: 'ryze-field' },
      h(Label, { htmlFor: id }, title), h(Input, { id, value, onChange: e => setter(e.target.value), disabled: !!busy,
        'aria-describedby': help ? id + '-help' : undefined, ...props }), help && h('p', { id: id + '-help', className: 'ryze-help' }, help));
    const button = (label, action, disabled = false, secondary = false) => h(Button, {
      type: 'button', disabled: !!busy || disabled, outlined: secondary, onClick: action
    }, label);
    const check = (id, checked, setter, label) => h('label', { className: 'ryze-check', htmlFor: id },
      h('input', { id, type: 'checkbox', checked, disabled: !!busy, onChange: e => setter(e.target.checked) }), h('span', null, label));
    const form = (submit, ...children) => h('form', { onSubmit: e => { e.preventDefault(); submit(); } }, ...children);
    const submit = (label, disabled) => h(Button, { type: 'submit', disabled: !!busy || disabled }, label);
    const navigate = next => { if (next === 1) setStep(1); focusView.current = true; setTab(next); setError(''); setNotice(''); };
    const changeStep = next => { setInspected(''); focusView.current = true; setStep(next); setTab(next === 3 ? 3 : 1); setError(''); setNotice(''); };
    async function choose(instanceName, creating) {
      const result = await api(creating ? '/instances' : '/select', { name: instanceName, confirm: creating ? createOK : undefined });
      setConnection(result.instance); setCode(null); setPermit(false);
      await refresh(); setInspected(''); changeStep(2); setCreateOK(false);
    }
    async function generate(pairing) {
      const result = await api('/connect', pairing ? { number } : {});
      if (result.status === 'connected') { await checkConnection(); setNotice('WhatsApp conectado. Autorize seu número na próxima etapa.'); }
      else { const stamp = Date.now(); setNow(stamp); setCode({ ...result, expiresAt: stamp + result.expires_in * 1000 }); }
    }
    async function saveFirewall(activate) {
      await api(activate ? '/activate' : '/firewall', { allowed_users: owners, allowed_recipients: recipients, confirm: permit });
      const next = await refresh(); setOwners(next.allowed_users || ''); setRecipients(next.allowed_recipients || ''); setPermit(false);
      if (activate) await refreshDiagnostics();
      setNotice(activate ? 'Hermes ativado com firewall. Envie uma mensagem pelo seu número autorizado para testar.' : 'Firewall salvo. O canal só pode enviar para os destinatários da lista.');
    }
    const localFeedback = scope => feedbackScope === scope && h('div', { className: 'ryze-feedback' },
      error && h('p', { role: 'alert', tabIndex: -1, ref: feedback }, error),
      (busy || notice) && h('p', { role: 'status' }, busy || notice));
    const dirty = (changed, discard) => changed && h('div', { className: 'ryze-dirty' }, h('span', null, 'Alterações não salvas'), button('Descartar alterações', discard, false, true));
    const healthContent = state && h('section', { className: 'ryze-metrics', 'aria-labelledby': 'ryze-health-title' },
        h('h3', { id: 'ryze-health-title' }, 'Saúde do canal'),
        !state.enabled ? h('p', null, 'Canal pausado. Ative o Hermes para acompanhar o processamento; o WhatsApp pode continuar conectado.') :
        transportError ? h('p', { role: 'status' }, 'Não foi possível consultar o diagnóstico. Nova tentativa automática em 5 segundos; use “Atualizar” se o problema persistir.') :
        !transport ? h('p', { role: 'status' }, 'Consultando conexão e processamento…') : h(React.Fragment, null,
          h('dl', { className: 'ryze-health-list' },
            h('dt', null, 'WhatsApp'), h('dd', null, channelStates[transport.whatsapp_state] || 'Estado requer atenção'),
            h('dt', null, 'Transporte'), h('dd', null, transport.websocket_connected ? 'WebSocket conectado · webhook em paralelo' : transport.running ? 'WebSocket indisponível · webhook de contingência' : 'Conexão não confirmada'),
            h('dt', null, 'Processamento'), h('dd', null, transport.maintenance_active ? 'Manutenção: novas mensagens aguardam na fila' : transport.consumer_healthy ? 'Fila funcionando' : 'Processamento indisponível. Atualize o estado; se persistir, consulte o administrador da VPS.'),
            h('dt', null, 'Tarefas do Hermes neste canal'), h('dd', null, transport.native_activity?.known === true ? String(transport.native_activity.agent_tasks) : 'Não confirmado'),
            h('dt', null, 'Mensagens aguardando'), h('dd', null, String(transport.buffer_pending ?? 'Não confirmado')),
            h('dt', null, 'Áudios em preparação'), h('dd', null, String(transport.stt_waiting ?? 'Não confirmado'))),
          h('p', { className: 'ryze-help' }, 'Atualização automática a cada 5 segundos enquanto o painel está visível. Conexão não significa mensagem entregue.'),
          h(TimingDetails, { timings: transport.timings }),
          h('details', { className: 'ryze-details' }, h('summary', null, 'Atividade e confirmações de entrega'),
            h('p', null, 'Último evento: ', dateText(transport.last_event_at), '. Último envio: ', dateText(transport.last_send_at), '.'),
            h('p', { className: 'ryze-help' }, 'Recibos observados nos últimos 7 dias, desde a instalação desta versão. Falta de recibo não prova falha de entrega.'),
            h('dl', { className: 'ryze-health-list' },
              ...[['accepted','Aceitos pela API, sem recibo'],['delivered','Entregues'],['read','Lidos'],['played','Áudios reproduzidos']].flatMap(([key,label]) => [h('dt', { key:key+'-label' }, label), h('dd', { key }, String(transport.delivery_counts?.[key] ?? 0))])),
            h('p', null, 'Recibos com alerta: ', String(['retry','inactive','server_error'].reduce((sum,key) => sum + (transport.delivery_counts?.[key] || 0), 0)), '. Não há reenvio automático.'),
            h('h4', null, 'Mensagens para revisão'),
            transport.review_items?.length ? h('ul', null, ...transport.review_items.map(item => h('li', { key:item.reference },
              item.status === 'expired' ? 'Expirada' : 'Execução incerta', ' · referência ', h('code', null, item.reference), ' · ', dateText(item.created)))) : h('p', null, 'Nenhuma mensagem incerta ou expirada registrada.'),
            h('p', { className: 'ryze-help' }, 'Confira a conversa antes de enviar uma nova instrução. Registros incertos nunca são reexecutados automaticamente.'))));
    let content;
    if (!state) content = h('div', null, h('p', null, busy || 'Não foi possível carregar a configuração.'), !busy && button('Tentar novamente', () => run('Carregando…', refresh)));
    else if (step === 0) content = h(React.Fragment, null,
      h('h2', null, state.credential_saved ? 'Acesso RyzeAPI salvo' : 'Conecte sua conta RyzeAPI'),
      h('p', { className: 'ryze-intro' }, 'Use o token atual da RyzeAPI. Este acesso lista suas instâncias; ele ainda não conecta o WhatsApp nem autoriza comandos.'),
      state.credential_saved ? h('div', null,
        h('p', null, 'Credencial armazenada somente na VPS. O token não é reenviado para este navegador.'),
        button('Ir para instâncias', () => changeStep(1)),
        h('details', { className: 'ryze-details' }, h('summary', null, 'Trocar conta ou remover acesso local'),
          h('p', null, 'Isso remove a configuração local. Não exclui a instância na RyzeAPI e não desconecta o WhatsApp.'),
          state.enabled ? h('p', null, 'Pause o canal na etapa Hermes antes de alterar o acesso.') : h(React.Fragment, null,
            check('ryze-forget', forgetOK, setForgetOK, 'Quero remover as credenciais e a seleção salvas nesta VPS.'),
            button('Remover acesso local', () => run('Removendo acesso…', async () => { await api('/forget', { confirm: forgetOK }); hydrated.current = false; setItems([]); setConnection(null); setCode(null); setOwners(''); setForgetOK(false); await refresh(); }), !forgetOK, true)))) :
      form(() => run('Validando token na RyzeAPI…', async () => {
        const result = await api('/account', { token, kind }); setToken(''); setItems(result.instances); setListLoaded(true); await refresh(); changeStep(1);
      }),
        h('fieldset', { className: 'ryze-token-kind', disabled: !!busy }, h('legend', null, 'Tipo de credencial'),
          ...[['account', 'TokenAccount — conta completa'], ['instance', 'TokenInstance — uma instância']].map(([value, label]) => h('label', { key: value },
            h('input', { type: 'radio', name: 'ryze-kind', value, checked: kind === value, onChange: () => setKind(value) }), label))),
        field('ryze-token', kind === 'account' ? 'TokenAccount' : 'TokenInstance', token, setToken,
          { type: 'password', autoComplete: 'new-password', spellCheck: false, required: true, maxLength: 4096 }, 'Cole o token, sem “Bearer”. Ele será validado antes de ser salvo.'),
        submit('Validar e continuar', !token.trim())));
    else if (step === 1) content = h(React.Fragment, null,
      h('h2', null, 'Escolha a instância do Hermes'),
      h('p', { className: 'ryze-intro' }, 'Selecione uma instância existente ou crie uma nova. Nenhuma instância antiga será reaproveitada automaticamente.'),
      state.instance && h('p', null, 'Selecionada: ', h('strong', null, state.instance)),
      button('Atualizar lista', () => run('Buscando instâncias…', async () => { const result = await api('/instances'); setItems(result.instances); setListLoaded(true); }), false, true),
      items.length ? form(() => run('Selecionando instância…', () => choose(choice, false)),
        h('div', { className: 'ryze-field' }, h(Label, { htmlFor: 'ryze-instance' }, 'Instâncias disponíveis'),
          h('select', { id: 'ryze-instance', value: choice, disabled: !!busy || state.enabled, onChange: e => setChoice(e.target.value), required: true },
            h('option', { value: '' }, 'Selecione uma instância'), ...items.map(i => h('option', { value: i.name, key: i.name }, i.name + ' · ' + states[i.status])))),
        submit('Usar esta instância', !choice || state.enabled)) : h('p', { className: 'ryze-help' }, listLoaded ? 'Nenhuma instância encontrada para este acesso. Você pode criar uma abaixo com TokenAccount.' : 'Use “Atualizar lista” para consultar as instâncias disponíveis na sua conta.'),
      state.instance && button('Continuar com ' + state.instance, () => changeStep(2), false, true),
      state.enabled ? h('p', null, 'O Hermes está habilitado. Pause o canal antes de trocar a instância.') :
      state.credential_kind === 'account' ? h('details', { className: 'ryze-details' }, h('summary', null, 'Criar uma nova instância'),
        form(() => run('Criando instância na RyzeAPI…', () => choose(name, true)),
          field('ryze-name', 'Nome da nova instância', name, setName, { required: true, maxLength: 100, pattern: '[A-Za-z0-9_-]+', autoComplete: 'off' }, 'Letras, números, hífen ou sublinhado. Exemplo: hermes-demo.'),
          check('ryze-create-ok', createOK, setCreateOK, 'Autorizo criar esta instância usando a cota da minha conta RyzeAPI.'),
          submit('Criar e selecionar', !name || !createOK))) : h('p', { className: 'ryze-help' }, 'Para criar instâncias, conecte a conta com um TokenAccount.'));
    else if (step === 2) content = h(React.Fragment, null,
      h('h2', null, connected ? 'WhatsApp conectado' : 'Conecte o WhatsApp'),
      h('p', { className: 'ryze-intro' }, 'Instância ', h('strong', null, state.instance), ' · ', states[connection?.status] || 'Estado não confirmado'),
      h('div', { className: 'ryze-connection ' + (connected ? 'is-connected' : 'is-waiting'), key: connected ? 'connected' : 'waiting', role: 'status', 'aria-live': 'polite' },
        connected ? h('svg', { className: 'ryze-connected-mark', width: 36, height: 36, viewBox: '0 0 36 36', fill: 'none', 'aria-hidden': true },
          h('circle', { cx: 18, cy: 18, r: 16, stroke: 'currentColor', strokeWidth: 1.5 }),
          h('path', { d: 'M10 18l5 5 11-11', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' })) : h('span', { className: 'ryze-connection-spinner', 'aria-hidden': true }),
        h('div', null, h('strong', null, connected ? 'WhatsApp conectado' : 'Aguardando conexão do WhatsApp'),
          h('p', { className: 'ryze-help' }, connected ? 'Conexão confirmada pela RyzeAPI. O QR foi removido com segurança.' : code ? 'Escaneie o QR. Esta tela confirma automaticamente quando conectar.' : 'Gere um QR Code para iniciar a conexão.'))),
      h('p', { className: 'ryze-poll-note' }, pollMessage, ' Continua verificando enquanto esta etapa estiver aberta e visível.'),
      connected ? h('div', null, h('p', null, 'WhatsApp conectado', connection.number ? ' · +' + connection.number : '', active ? '. Hermes ativo neste canal.' : '. Falta autorizar quem pode comandar o Hermes.'),
        button(active ? 'Ver estado do Hermes' : 'Configurar firewall e ativar', () => changeStep(3))) : h(React.Fragment, null,
        h('p', null, 'No WhatsApp do celular, abra Configurações → Dispositivos conectados → Conectar dispositivo.'),
        button(code ? 'Gerar novo QR Code' : 'Gerar QR Code', () => run('Solicitando QR Code… Pode levar até um minuto.', () => generate(false))),
        code && h('div', { className: 'ryze-code' }, remaining > 0 ? h(React.Fragment, null,
          code.qr ? h('img', { src: code.qr, alt: 'QR Code para conectar a instância WhatsApp selecionada', width: 256, height: 256 }) : h('code', { className: 'ryze-pairing' }, code.pairing_code),
          h('p', { role: 'timer', 'aria-live': 'off' }, 'Código disponível por até ' + remaining + ' s.')) :
          h('p', { role: 'status' }, 'Código expirado. Gere um novo código para continuar.')),
        h('details', { className: 'ryze-details' }, h('summary', null, 'Conectar com código em vez de QR'),
          form(() => run('Solicitando código de pareamento…', () => generate(true)),
            field('ryze-pair-number', 'Número do WhatsApp desta instância', number, setNumber,
              { type: 'tel', inputMode: 'numeric', required: true, pattern: '[0-9]{10,15}', maxLength: 15 }, 'DDI + DDD + número, somente dígitos. Este não é o número pessoal que autoriza comandos.'),
            submit('Gerar código de pareamento', !number)))),
      h('div', { className: 'ryze-actions' }, button('Atualizar conexão', () => run('Consultando conexão…', checkConnection), false, true)));
    else content = h(React.Fragment, null,
      h('h2', null, state.enabled ? 'Hermes habilitado neste canal' : 'Hermes protegido por contatos autorizados'),
      h('p', { className: 'ryze-intro' }, state.enabled ? 'A configuração está salva. Consulte Métricas para confirmar o funcionamento do transporte e do processamento.' : 'Conectar o WhatsApp não libera o agente. Configure as duas permissões antes de ativar.'),
      state.enabled && h('div', null,
        !active && h('p', { role: 'alert' }, 'A configuração está habilitada, mas a execução ainda não foi confirmada. Atualize o estado ou pause o canal.'),
        h('p', null, 'Números autorizados: ', state.allowed_users),
        button('Atualizar estado', () => run('Verificando gateway…', async () => { await refresh(); await refreshDiagnostics(); }), false, true),
        h('div', { className: 'ryze-actions' }, button('Pausar Hermes neste canal', () => run('Pausando canal…', async () => { await api('/pause', {}); await refresh(); setNotice('Canal pausado. Novas mensagens não serão processadas; o WhatsApp continua conectado.'); }), false, true)),
        h('p', { className: 'ryze-help' }, 'Pausar não encerra tarefas já aceitas pelo agente.')),
      h('section', { className: 'ryze-firewall', 'aria-labelledby': 'ryze-buffer-title' },
        h('h3', { id: 'ryze-buffer-title' }, 'Buffer de mensagens'),
        localFeedback('buffer'),
        dirty(buffer !== String(state.buffer_seconds ?? 10), () => setBuffer(String(state.buffer_seconds ?? 10))),
        h('p', null, 'Reúna textos, áudios, imagens e arquivos antes de pedir uma resposta à IA. Cada nova mensagem do mesmo contato reinicia a espera.'),
        form(() => run('Salvando buffer…', async () => {
          const result = await api('/buffer', { buffer_seconds: Number(buffer) });
          setBuffer(String(result.buffer_seconds)); await refresh();
          setNotice(result.buffer_seconds === 0 ? 'Buffer salvo: sem espera. Novas mensagens seguem imediatamente para o Hermes.' :
            'Buffer salvo: o Hermes aguarda ' + result.buffer_seconds + ' segundos após a última mensagem. Aplicado sem reiniciar o canal.');
        }),
          field('ryze-buffer', 'Tempo de espera (segundos)', buffer, setBuffer,
            { type: 'number', min: 0, max: 60, step: 1, required: true, inputMode: 'numeric' },
            'De 0 a 60 segundos. Padrão: 10. Use 0 para não esperar. O valor salvo também vale para o lote que ainda está aguardando.'),
          h('div', { className: 'ryze-actions' }, submit('Salvar buffer', !/^\d+$/.test(buffer) || Number(buffer) > 60),
            h('span', { className: 'ryze-help' }, 'Salvo: ', (state.buffer_seconds ?? 10) === 0 ? 'sem espera' : (state.buffer_seconds ?? 10) + ' s'))),
        h('p', { className: 'ryze-help' }, 'Ao terminar a espera, o lote segue junto para análise. Limite de segurança: 2 minutos ou 20 mensagens por lote. Comandos como /stop não aguardam o buffer.')),
      h('section', { className: 'ryze-firewall', 'aria-labelledby': 'ryze-transcription-title' },
        h('h3', { id: 'ryze-transcription-title' }, 'Transcrição de áudios'),
        localFeedback('transcription'),
        dirty(echoTranscripts !== (state.echo_transcripts ?? true), () => setEchoTranscripts(state.echo_transcripts ?? true)),
        form(() => run('Salvando transcrições…', async () => {
          const result = await api('/transcription', { echo_transcripts: echoTranscripts });
          setEchoTranscripts(result.echo_transcripts); await refresh();
          setNotice(result.echo_transcripts ? 'Preferência salva: as transcrições serão enviadas na conversa. Aplicado sem reiniciar o canal.' :
            'Preferência salva: o Hermes continuará entendendo os áudios, sem enviar a transcrição automática na conversa. Aplicado sem reiniciar o canal.');
        }),
          h('label', { className: 'ryze-check', htmlFor: 'ryze-echo-transcripts' },
            h('input', { id: 'ryze-echo-transcripts', type: 'checkbox', checked: echoTranscripts,
              disabled: !!busy, 'aria-describedby': 'ryze-transcription-help', onChange: e => setEchoTranscripts(e.target.checked) }),
            h('span', null, 'Enviar transcrições na conversa')),
          h('p', { id: 'ryze-transcription-help', className: 'ryze-help' },
            'Marcada: envia a transcrição de cada áudio que conseguir transcrever. Desmarcada: usa a transcrição para entender o áudio e responder, sem publicar uma cópia automática. A compreensão do áudio continua ativa.'),
          h('div', { className: 'ryze-actions' }, submit('Salvar transcrições'),
            h('span', { className: 'ryze-help' }, 'Salvo: ', (state.echo_transcripts ?? true) ? 'enviar na conversa' : 'somente para a IA'))),
        h('p', { className: 'ryze-help' }, 'Os áudios mantêm sua posição na sequência de mensagens. Esta opção não altera o buffer nem o firewall.')),
      h('section', { className: 'ryze-firewall', 'aria-labelledby': 'ryze-firewall-title' },
        h('h3', { id: 'ryze-firewall-title' }, 'Firewall de contatos'),
        localFeedback('firewall'),
        dirty(owners !== (state.allowed_users || '') || recipients !== (state.allowed_recipients || ''), () => { setOwners(state.allowed_users || ''); setRecipients(state.allowed_recipients || ''); setPermit(false); }),
        h('p', null, 'Mensagens privadas só podem ser enviadas aos contatos desta lista. Autorizar o recebimento não permite comandar o agente. Grupos têm permissões próprias na seção abaixo.'),
        form(() => run(state.enabled || !connected ? 'Salvando firewall…' : 'Ativando com firewall…', () => saveFirewall(!state.enabled && connected)),
          h(Contacts, { owners, recipients, disabled: !!busy, onChange: (a, b) => { setOwners(a); setRecipients(b); setPermit(false); } }),
          check('ryze-permit', permit, setPermit, 'Confirmo quem pode dar comandos e receber mensagens privadas. Outros contatos devem ser bloqueados.'),
          !connected && h('p', { className: 'ryze-help' }, 'Você pode salvar o firewall agora. Conecte o WhatsApp para ativar o Hermes.'),
          state.enabled && h('p', { className: 'ryze-help' }, 'Salvar com o canal ativo reinicia o gateway para aplicar as permissões. Em caso de falha, o canal é pausado.'),
          h('div', { className: 'ryze-actions' }, submit(!state.enabled && connected ? 'Salvar e ativar Hermes' : 'Salvar firewall', !owners || !recipients || !permit),
            !state.enabled && connected && button('Salvar sem ativar', () => run('Salvando firewall…', () => saveFirewall(false)), !owners || !recipients || !permit, true)))),
      h(Groups, { instance: state.instance, drafts: groupDrafts, setDrafts: setGroupDrafts, picked: pickedGroups, setPicked: setPickedGroups, disabled: !!busy }));
    const link = (label, action) => h('button', { type: 'button', className: 'ryze-link', disabled: !!busy, onClick: action }, label, icon('arrow'));
    const instanceTable = rows => rows.length ? h('table', { className: 'ryze-table ryze-instance-table' },
      h('thead', null, h('tr', null, ...['Nome da instância', 'Status do WhatsApp', 'Vinculação ao Hermes', 'Ações'].map(label => h('th', { key: label, scope: 'col' }, label)))),
      h('tbody', null, ...rows.map(item => h('tr', { key: item.name },
        h('th', { scope: 'row', 'data-label': 'Instância' }, item.name),
        h('td', { 'data-label': 'WhatsApp' }, h('span', { className: 'ryze-dot ' + (item.status === 'connected' ? 'is-good' : 'is-muted'), 'aria-hidden': true }), states[item.status] || 'Não confirmado'),
        h('td', { 'data-label': 'Hermes' }, item.name === state?.instance ? 'Instância do Hermes' : 'Não vinculada'),
        h('td', { 'data-label': 'Ações' }, link('Ver detalhes', () => { setInspected(item.name); navigate(1); if (item.name === state.instance) setStep(2); })))))) :
      h('p', { className: 'ryze-empty' }, listLoaded ? 'Nenhuma outra instância nesta conta.' : 'A lista ainda não foi consultada. Use Atualizar para tentar novamente.');
    const overview = state && h(React.Fragment, null,
      h('section', { className: 'ryze-channel', 'aria-label': 'Saúde do canal' },
        h('div', { className: 'ryze-channel-lead' }, h('span', { className: active ? 'is-good' : '' }, icon(active ? 'check' : 'info')),
          h('div', null, h('h3', null, active ? 'Seu canal está pronto' : !state.instance ? 'Vamos conectar seu canal' : !state.enabled ? 'Hermes está pausado' : transportError || !transport ? 'Estado não confirmado' : transport.maintenance_active ? 'Canal em manutenção' : 'Seu canal precisa de atenção'),
            h('p', { className: 'ryze-help' }, 'Conexão não confirma entrega.'))),
        h('dl', { className: 'ryze-channel-facts' }, ...[
          ['WhatsApp', channelStates[transport?.whatsapp_state] || states[connection?.status] || 'Não confirmado', transport?.whatsapp_state ? transport.whatsapp_state === 'connected' : connected],
          ['Transporte', transport?.websocket_connected ? 'WebSocket' : transport?.running ? 'Webhook de contingência' : 'Não confirmado', transport?.websocket_connected],
          ['Hermes', !state.enabled ? 'Pausado' : active ? 'Ativo' : transport?.maintenance_active ? 'Manutenção' : 'Não confirmado', active]
        ].map(([label, value, good]) => h('div', { key: label }, h('dt', null, h('span', { className: 'ryze-dot ' + (good ? 'is-good' : 'is-muted'), 'aria-hidden': true }), label, good ? ' ' + value : ''), h('dd', null, label === 'Transporte' && good ? 'Conectado' : value))))),
      !state.credential_saved && h('div', { className: 'ryze-actions' }, button('Conectar conta RyzeAPI', () => changeStep(0))),
      state.credential_saved && !state.instance && h('div', { className: 'ryze-actions' }, button('Escolher instância', () => changeStep(1))),
      state.instance && !state.enabled && h('div', { className: 'ryze-actions' }, button('Configurar canal', () => changeStep(connected ? 3 : 2))),
      h('div', { className: 'ryze-overview-columns' },
        h('section', { className: 'ryze-processing' }, h('h3', null, 'Processamento'),
          h('dl', { className: 'ryze-counts' }, h('div', null, h('dd', null, transport?.buffer_pending ?? '—'), h('dt', null, 'mensagens aguardando')),
            h('div', null, h('dd', null, transport?.native_activity?.known ? transport.native_activity.agent_tasks : '—'), h('dt', null, 'tarefas em processamento'))),
          h('table', { className: 'ryze-table ryze-summary-timings' }, h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Tempo por etapa'), h('th', { scope: 'col' }, 'Duração média'))),
            h('tbody', null, ...[['buffer', 'Buffer'], ['stt_execution', 'Transcrição'], ['agent_to_first_send', 'Primeira resposta']].map(([key, label]) => h('tr', { key }, h('th', { scope: 'row' }, label), h('td', null, durationText(transport?.timings?.[key]?.mean_ms)))))),
          link('Ver todas as métricas', () => navigate(2))),
        h('section', { className: 'ryze-config-summary' }, h('h3', null, 'Configuração do Hermes'),
          h('dl', null, ...[
            ['Buffer', (state.buffer_seconds ?? 10) + ' s', 'Tempo para agrupar mensagens antes do processamento.'],
            ['Transcrições', state.echo_transcripts === false ? 'Só para IA' : 'Na conversa', state.echo_transcripts === false ? 'As transcrições são enviadas apenas para a IA do Hermes.' : 'As transcrições também são enviadas na conversa.'],
            ['Permissões', 'Restritas', 'O Hermes pode responder apenas conforme as permissões definidas.']
          ].map(([label, value, help]) => h('div', { key: label }, h('dt', null, label), h('dd', null, value), h('dd', { className: 'ryze-help' }, help)))),
          button(h(React.Fragment, null, icon('settings'), 'Editar configurações'), () => { setStep(3); navigate(3); }, false, true))),
      h('section', { className: 'ryze-other' }, h('h3', null, 'Outras instâncias'), instanceTable(items.filter(item => item.name !== state.instance))),
      h('footer', { className: 'ryze-footer' }, icon('info'), h('p', null, 'Outras instâncias não executam o Hermes automaticamente.')));
    const inspectedItem = items.find(item => item.name === inspected);
    let pageContent = content;
    if (state) {
      if (tab === 0) pageContent = overview;
      else if (tab === 2) pageContent = h(React.Fragment, null,
        h('p', { className: 'ryze-intro' }, 'Diagnóstico da instância do Hermes: ', h('strong', null, state.instance || 'nenhuma selecionada'), '. As outras instâncias não compartilham estas métricas.'),
        h('p', { className: 'ryze-help' }, updatedAt ? 'Última consulta bem-sucedida: ' + new Date(updatedAt).toLocaleString('pt-BR') + '.' : 'Aguardando a primeira consulta de diagnóstico.'), healthContent);
      else if (tab === 3 && !state.instance) pageContent = h('div', null, h('p', null, 'Escolha uma instância antes de configurar o Hermes.'), button('Escolher instância', () => changeStep(state.credential_saved ? 1 : 0)));
      else if (tab === 1) {
        if (inspected && inspected !== state.instance) pageContent = h('section', { className: 'ryze-instance-detail' },
          link('Voltar à lista', () => { setInspected(''); changeStep(1); }), h('h3', null, inspected),
          inspectedItem ? h('dl', { className: 'ryze-health-list' }, h('dt', null, 'WhatsApp'), h('dd', null, states[inspectedItem.status] || 'Não confirmado'),
            h('dt', null, 'Número conectado'), h('dd', null, inspectedItem.number ? '+' + inspectedItem.number : 'Não informado'),
            h('dt', null, 'Perfil'), h('dd', null, inspectedItem.profile_name || 'Não informado'), h('dt', null, 'Hermes'), h('dd', null, 'Não vinculada')) : h('p', null, 'Esta instância não está na última lista. Atualize para consultar novamente.'),
          h('p', { className: 'ryze-help' }, 'Consulta somente. Abrir estes detalhes não conecta nem ativa o Hermes nesta instância.'),
          state.enabled ? button('Ver configurações do canal ativo', () => changeStep(3), false, true) : button('Escolher vínculo do Hermes', () => { setChoice(inspected); setInspected(''); changeStep(1); }, false, true));
        else if (step === 1 && state.credential_saved) pageContent = h(React.Fragment, null,
          h('p', { className: 'ryze-intro' }, 'Todas as instâncias da sua conta. Apenas ', h('strong', null, state.instance || 'a instância que você escolher'), ' pode executar o Hermes neste canal.'),
          instanceTable(items), h('div', { className: 'ryze-actions' }, state.instance && button('Abrir WhatsApp do Hermes', () => changeStep(2))),
          h('details', { className: 'ryze-details' }, h('summary', null, 'Selecionar ou criar instância para o Hermes'), content));
        else if (step === 2) pageContent = h(React.Fragment, null, link('Voltar à lista', () => changeStep(1)), content);
      }
    }
    return h('section', { className: 'ryze-page', lang: 'pt-BR', 'aria-labelledby': 'ryze-title', 'aria-busy': !!busy },
      h('header', { className: 'ryze-header' }, h('div', null, h('h1', { id: 'ryze-title' }, 'RyzeAPI'), h('p', null, 'Seu WhatsApp, conectado ao Hermes.')),
        button(h(React.Fragment, null, icon('user'), 'Conta pessoal'), () => changeStep(0), false, true)),
      h('nav', { className: 'ryze-tabs', 'aria-label': 'Navegação RyzeAPI' }, ...tabs.map((label, index) => h('button', {
        key: label, type: 'button', 'aria-current': tab === index ? 'page' : undefined, disabled: !!busy,
        onClick: () => { setInspected(''); if (index === 3) setStep(3); navigate(index); if (index === 1 && !state?.credential_saved) setStep(0); }
      }, label))),
      h('div', { className: 'ryze-title-row' }, h('h2', { tabIndex: -1, ref: viewTitle }, tabs[tab]),
        h('div', { className: 'ryze-title-actions' }, state?.instance && h('div', null, h('label', { htmlFor: 'ryze-inspect' }, 'Instância selecionada'),
          h('select', { id: 'ryze-inspect', value: tab === 1 && inspected ? inspected : state.instance, disabled: !!busy, onChange: e => { const n = e.target.value; setInspected(n); navigate(1); if (n === state.instance) setStep(2); } },
            ...[state.instance, ...items.map(i => i.name).filter(n => n !== state.instance)].map(n => h('option', { key: n, value: n }, n)))),
          button(h(React.Fragment, null, icon('refresh'), 'Atualizar'), () => run('Atualizando…', async () => { const next = await refresh(); if (next.instance) await checkConnection(); if (next.enabled) await refreshDiagnostics(); if (next.credential_saved) { const result = await api('/instances'); setItems(result.instances); setListLoaded(true); } }), false, true))),
      localFeedback('global'),
      h('div', { className: 'ryze-main' }, pageContent));
  }
  window.__HERMES_PLUGINS__.register('ryzeapi', App);
})();
