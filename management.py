"""Dashboard control plane. Only allowlisted data is ever returned to the browser."""
import fcntl
import asyncio, base64, hashlib, os, re, secrets, time, shutil
from contextlib import asynccontextmanager
from urllib.parse import quote
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from . import settings
from .core import allowed_numbers, phone, authorized_phone
from .client import RyzeClient, RyzeError
from .telemetry import EVENTS
from .groups import GroupStore, group_id
from . import infrastructure
from .webhooks import confirmed, owned_hook

mutation_lock = asyncio.Lock()
upstream_clients = None

@asynccontextmanager
async def mutation():
    # Dashboard and Webapp can run in different processes against the same profile.
    async with mutation_lock:
        folder = settings.directory()
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        with (folder / 'control.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HTTPException(409, 'Outra configuração está em andamento. Atualize o estado.') from None
            yield


@asynccontextmanager
async def lifespan(app):
    global upstream_clients
    upstream_clients = {}
    try: yield
    finally:
        clients, upstream_clients = upstream_clients, None
        for client in clients.values(): await client.close()

async def protect(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    deployment = infrastructure.load()
    session = getattr(request.state, 'session', None)
    hosted = getattr(request.state, 'hosted_http_authenticated', None)
    if hosted is False:
        raise HTTPException(401, 'Entre no Hermes para administrar o RyzeAPI.')
    external = bool(session or getattr(request.app.state, 'auth_required', False)
                    or deployment['owner_subject'] or deployment['public_origin'].startswith('https://'))
    if external:
        if session is None:
            raise HTTPException(401, 'Entre no Hermes com a conta do proprietário.')
        if (not deployment['owner_subject']
                or deployment['owner_subject'] != getattr(session, 'user_id', None)
                or deployment['owner_issuer'] != getattr(session, 'issuer', None)):
            raise HTTPException(403, 'Conta OIDC sem permissão para administrar o RyzeAPI.')
    if request.method != 'GET':
        if request.headers.get('origin') != deployment['public_origin']:
            raise HTTPException(403, 'Abra esta configuração pelo painel Hermes autenticado.')
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Envie os dados em JSON.')
        if not external and request.headers.get('x-ryze-ui') != '1':
            if (await body(request)).get('_ryze_ui') is not True:
                raise HTTPException(403, 'Abra esta configuração pelo painel Hermes autenticado.')

router = APIRouter(dependencies=[Depends(protect)], lifespan=lifespan)

async def body(request):
    if len(await request.body()) > 16384: raise HTTPException(413, 'Formulário muito grande.')
    try: value = await request.json()
    except Exception: raise HTTPException(400, 'Formulário inválido.') from None
    if not isinstance(value, dict): raise HTTPException(400, 'Formulário inválido.')
    return value

def text(value, key, maximum=100):
    result = value.get(key, '')
    if not isinstance(result, str) or len(result) > maximum:
        raise HTTPException(400, 'Campo inválido: ' + key)
    return result.strip()

def valid_name(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise HTTPException(400, 'Use de 1 a 100 letras, números, hífen ou sublinhado no nome da instância.')
    return value

def credential(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise HTTPException(400, 'Token inválido. Cole somente o token, sem espaços ou quebras de linha.')
    return value

async def upstream(token, method, path, *, payload=None, params=None, timeout=25):
    token = credential(token)
    key = hashlib.sha256(token.encode()).hexdigest()
    pooled = upstream_clients is not None
    client = upstream_clients.get(key) if pooled else None
    if client is None:
        client = RyzeClient('control-plane',token,max_body=4*1024*1024,success_codes=(200,201))
        if pooled and len(upstream_clients)<4: upstream_clients[key] = client
        else: pooled = False
    try:
        # GET /instance/connect generates credentials: do not repeat it automatically.
        return await client.envelope(method,path,payload=payload,params=params,timeout=timeout,
                                     retry_get=not path.startswith('/api/instance/connect/'))
    except RyzeError as exc:
        messages = {401: 'Token recusado pela RyzeAPI. Confira a credencial atual.',
                403: 'A RyzeAPI recusou a ação. Confira a permissão do token e a cota de instâncias.',
                404: 'Instância não encontrada na RyzeAPI. Atualize a lista.',
                409: 'A RyzeAPI informou um conflito. Atualize a lista antes de tentar novamente.',
                429: 'Limite de requisições da RyzeAPI atingido. Aguarde antes de atualizar.'}
        status = 400 if exc.status == 401 else exc.status if exc.status in messages else 502
        raise HTTPException(status,
                            messages.get(exc.status, 'A RyzeAPI não confirmou a operação. Verifique o estado antes de repetir.')) from None
    finally:
        if not pooled: await client.close()

def public_instance(item):
    connection = item.get('connection') or {}
    profile = item.get('profile') or {}
    if not isinstance(connection, dict) or not isinstance(profile, dict):
        raise HTTPException(502, 'Dados de conexão inválidos na resposta da RyzeAPI.')
    state = connection.get('state') or item.get('status') or 'unknown'
    if state not in ('connected', 'connecting', 'disconnected', 'loggedout', 'qr'): state = 'unknown'
    return {'name': str(item.get('name', ''))[:100], 'status': state,
            'number': phone(connection.get('numberJid') or item.get('numberJid')),
            'profile_name': str(profile.get('name') or '')[:150]}

async def instances(token, name=None):
    data = await upstream(token, 'GET', '/api/instance/list', params={'instanceName': name} if name else None)
    result = data.get('instances')
    if not isinstance(result, list) or any(not isinstance(i, dict) for i in result):
        raise HTTPException(502, 'Lista de instâncias inválida na resposta da RyzeAPI.')
    return result

def editable(value):
    if value.get('enabled') or value.get('hook_pending') or value.get('webhook_configured'): raise HTTPException(409, 'Pause o Hermes neste canal antes de trocar conta ou instância.')

def selected(value):
    if not value.get('instance') or not value.get('instance_token'):
        raise HTTPException(409, 'Selecione uma instância primeiro.')
    return valid_name(value['instance']), credential(value['instance_token'])

def firewall_fields(data, *, paused=False):
    raw = text(data, 'allowed_users', 300)
    outbound = text(data, 'allowed_recipients', 1000) if 'allowed_recipients' in data else raw
    try:
        numbers = set() if paused and not raw else allowed_numbers(raw)
        recipients = set() if paused and not outbound else allowed_numbers(outbound)
    except ValueError:
        raise HTTPException(400, 'Informe números com DDI/DDD separados por vírgula. Para ativar, inclua ao menos um contato que possa comandar e receber.') from None
    if not all(authorized_phone(number, recipients) for number in numbers):
        raise HTTPException(400, 'Inclua os números que comandam o Hermes também na lista de quem pode receber respostas.')
    if data.get('confirm') is not True:
        raise HTTPException(400, 'Confirme as permissões do firewall de contatos.')
    return {'allowed_users': ','.join(sorted(numbers)), 'allowed_recipients': ','.join(sorted(recipients))}

async def read_health(value):
    if not value.get('webhook_secret'):
        return {}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            result = await client.get(infrastructure.health_url(),
                                      headers={'Authorization': 'Bearer '+value['webhook_secret']})
        result.raise_for_status()
        data = result.json()
        if isinstance(data, dict) and data.get('instance') == value.get('instance'):
            return data
    except (httpx.HTTPError, ValueError):
        pass
    return {}


async def runtime(value):
    return (await read_health(value)).get('running') is True


async def restart():
    deployment = infrastructure.load()
    managed = deployment['lifecycle'] == 'coolify' or (
        deployment['lifecycle'] == 'auto' and not shutil.which('systemctl'))
    if managed:
        # Coolify owns this process. The durable configuration is picked up at redeploy.
        return False
    env = dict(os.environ, XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}',
               DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{os.getuid()}/bus')
    proc = await asyncio.create_subprocess_exec('systemctl', '--user', 'restart', infrastructure.load()['gateway_service'],
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=env)
    try: result = await asyncio.wait_for(proc.wait(), timeout=80)
    except asyncio.TimeoutError:
        proc.kill(); await proc.wait()
        raise HTTPException(503, 'O gateway ainda não confirmou o reinício. Confira seu estado antes de tentar novamente.') from None
    if result: raise HTTPException(503, 'Não foi possível reiniciar o gateway. A configuração foi salva; confira o serviço Hermes.')

@router.get('/state')
async def state():
    value = settings.load()
    group_count = 0
    if value.get('instance') and (settings.directory() / 'groups.db').exists():
        with GroupStore(settings.directory(), value['instance']) as store:
            group_count = store.permitted_count()
    return {'saved_groups': group_count, 'credential_saved': bool(value.get('account_token')), 'credential_kind': value.get('credential_kind', 'account'),
            'instance': value.get('instance', ''), 'allowed_users': value.get('allowed_users', ''),
            'allowed_recipients': settings.recipient_list(value),
            'buffer_seconds': settings.buffer_seconds(value),
            'echo_transcripts': settings.echo_transcripts(value),
            'enabled': bool(value.get('enabled')), 'runtime_running': await runtime(value),
            'hook_pending': bool(value.get('hook_pending')), 'webhook_configured': bool(value.get('webhook_configured')), 'webhook_url': infrastructure.load()['webhook_url']}

@router.get('/transport')
async def transport_health():
    value = settings.load()
    data = await read_health(value)
    if not data:
        return {'running': False, 'websocket_connected': False}
    return {k: data.get(k) for k in ('running', 'websocket_connected', 'websocket_reconnects',
            'transport', 'last_event_at', 'last_send_at', 'counters', 'buffer_seconds', 'buffer_pending', 'echo_transcripts',
            'consumer_healthy', 'consumer_error', 'queue_counts', 'oldest_pending_seconds',
            'active_batches', 'pending_ttl_seconds', 'stt_busy', 'stt_waiting', 'orphaned_preparations',
            'ws_ingress_pending','ws_ingress_bytes','timings','early_receipts_pending','native_activity','maintenance_active',
            'whatsapp_state', 'whatsapp_observed_at', 'delivery_counts', 'review_items')}

@router.get('/groups')
async def list_groups():
    value = settings.load(); name, _ = selected(value)
    with GroupStore(settings.directory(),name) as store:
        return {'instance':name,'groups':store.list()}

@router.post('/groups/sync')
async def sync_groups(request: Request):
    await body(request)
    async with mutation():
        value = settings.load(); name, token = selected(value)
        result = await upstream(token,'GET',f'/api/group/list/{name}',params={'includeMembers':'false'},timeout=65)
        try:
            with GroupStore(settings.directory(),name) as store:
                groups = store.sync(result.get('groups'))
        except ValueError: raise HTTPException(502,'Lista de grupos inválida. O catálogo anterior foi preservado.') from None
    return {'instance':name,'groups':groups}

async def enable_group_events(token, name):
    await upstream(token, 'POST', f'/api/instance/settings/{name}', payload={'ignoreGroupMessages': False})
    readback = await upstream(token, 'GET', f'/api/instance/getSettings/{name}')
    if (readback.get('settings') or {}).get('ignoreGroupMessages') is not False:
        raise HTTPException(502, 'A RyzeAPI não confirmou o recebimento de grupos.')


@router.post('/groups/policy')
async def group_policy(request: Request):
    data = await body(request)
    jid, mode, trigger, senders = (text(data,k) for k in ('jid','mode','trigger','senders'))
    if not group_id(jid) or mode not in {'blocked','listen','respond'} or trigger not in {'mentions','all'} or senders not in {'authorized','all'}:
        raise HTTPException(400,'Escolha um grupo e permissões válidas.')
    if data.get('confirm') is not True: raise HTTPException(400,'Confirme as permissões deste grupo.')
    async with mutation():
        value = settings.load(); name, token = selected(value)
        if data.get('instance')!=name: raise HTTPException(409,'A instância mudou. Atualize os grupos antes de salvar.')
        with GroupStore(settings.directory(),name) as store:
            old = store.policy(jid)
            if not old.get('present') and mode!='blocked': raise HTTPException(409,'Sincronize os grupos antes de liberar este grupo.')
            # Revoke first, before any network work. Restricted settings always apply locally.
            if mode=='blocked':
                try: store.configure(jid,mode,trigger,senders)
                except ValueError: raise HTTPException(404,'Grupo não encontrado.') from None
            else:
                if value.get('enabled') or value.get('webhook_configured'):
                    await enable_group_events(token, name)
                    if value.get('webhook_configured'):
                        await verify_hook(value, enabled=True)
                store.configure(jid,mode,trigger,senders)
            groups=store.list()
    return {'saved':True,'instance':name,'groups':groups}

@router.post('/buffer')
async def save_buffer(request: Request):
    data = await body(request)
    seconds = data.get('buffer_seconds')
    if type(seconds) is not int or not 0 <= seconds <= 60:
        raise HTTPException(400, 'Informe um número inteiro de 0 a 60 segundos. Use 0 para responder sem espera.')
    async with mutation():
        value = settings.load(); selected(value)
        value['buffer_seconds'] = seconds
        settings.save(value)
    return {'saved': True, 'buffer_seconds': seconds}

@router.post('/transcription')
async def save_transcription(request: Request):
    data = await body(request)
    enabled = data.get('echo_transcripts')
    if type(enabled) is not bool:
        raise HTTPException(400, 'Marque ou desmarque a opção de enviar transcrições e salve novamente.')
    async with mutation():
        value = settings.load(); selected(value)
        value['echo_transcripts'] = enabled
        settings.save(value)
    return {'saved': True, 'echo_transcripts': enabled}

@router.post('/account')
async def account(request: Request):
    data = await body(request)
    kind = text(data, 'kind')
    if kind not in ('account', 'instance'): raise HTTPException(400, 'Escolha TokenAccount ou TokenInstance.')
    token = credential(text(data, 'token', 4096))
    async with mutation():
        current = settings.load(); editable(current)
        items = await instances(token)
        # Validate response completely before replacing an existing usable credential.
        safe_items = [public_instance(i) for i in items]
        settings.save({'account_token': token, 'credential_kind': kind, 'enabled': False})
    return {'instances': safe_items}

@router.get('/instances')
async def list_instances():
    value = settings.load()
    if not value.get('account_token'): raise HTTPException(409, 'Conecte sua conta RyzeAPI primeiro.')
    return {'instances': [public_instance(i) for i in await instances(value['account_token'])]}

@router.post('/select')
async def select(request: Request):
    data = await body(request); name = valid_name(text(data, 'name'))
    async with mutation():
        value = settings.load(); editable(value)
        if not value.get('account_token'): raise HTTPException(409, 'Conecte sua conta primeiro.')
        items = await instances(value['account_token'], name)
        item = next((i for i in items if i.get('name') == name), None)
        if item is None: raise HTTPException(404, 'Esta instância não pertence ao acesso informado.')
        token = item.get('token') or (value['account_token'] if value.get('credential_kind') == 'instance' else None)
        if not token: raise HTTPException(502, 'A RyzeAPI não retornou o TokenInstance. Conecte usando o token da instância.')
        value.update(instance=name, instance_token=credential(token), webhook_configured=False,
                     webhook_secret=secrets.token_urlsafe(48), enabled=False)
        settings.save(value)
    return {'instance': public_instance(item)}

@router.post('/instances')
async def create(request: Request):
    data = await body(request); name = valid_name(text(data, 'name'))
    if data.get('confirm') is not True: raise HTTPException(400, 'Confirme a criação dentro da cota da sua conta.')
    async with mutation():
        value = settings.load(); editable(value)
        if value.get('credential_kind') != 'account' or not value.get('account_token'):
            raise HTTPException(409, 'Criar instâncias exige TokenAccount.')
        # Check first: ambiguous retries must never provision another instance silently.
        items = await instances(value['account_token'])
        if any(i.get('name') == name for i in items): raise HTTPException(409, 'Esse nome já existe. Selecione a instância na lista.')
        result = await upstream(value['account_token'], 'POST', '/api/instance/new',
            payload={'name': name, 'disableHistorySync': True, 'ignoreGroupMessages': True, 'ignoreStatus': True})
        item = result.get('instance')
        if not isinstance(item, dict) or item.get('name') != name or not item.get('token'):
            raise HTTPException(502, 'A criação não pôde ser confirmada. Atualize a lista antes de repetir.')
        value.update(instance=name, instance_token=credential(item['token']), enabled=False,
                     webhook_secret=secrets.token_urlsafe(48), webhook_configured=False)
        settings.save(value)
    return {'instance': public_instance(item)}

@router.post('/connect')
async def connect(request: Request):
    data = await body(request)
    number = text(data, 'number', 30)
    if number and not phone(number): raise HTTPException(400, 'Informe o número do WhatsApp com DDI e DDD, somente dígitos.')
    async with mutation():
        value = settings.load(); name, token = selected(value)
        result = await upstream(token, 'GET', f'/api/instance/connect/{quote(name, safe="")}',
            params={'number': phone(number)} if number else None, timeout=75)
    qr = result.get('qrCodeBase64', '')
    pairing = result.get('pairingCode', '')
    if qr:
        if not isinstance(qr, str) or len(qr) > 1500000:
            raise HTTPException(502, 'A RyzeAPI retornou um QR Code em formato não suportado.')
        encoded = qr.removeprefix('data:image/png;base64,')
        try: decoded = base64.b64decode(encoded, validate=True)
        except ValueError: raise HTTPException(502, 'QR Code inválido.') from None
        if not decoded.startswith(b'\x89PNG\r\n\x1a\n'): raise HTTPException(502, 'QR Code inválido.')
        qr = 'data:image/png;base64,' + encoded
    if pairing and (not isinstance(pairing, str) or not re.fullmatch(r'[A-Z0-9]{4}-?[A-Z0-9]{4}', pairing)):
        raise HTTPException(502, 'Código de pareamento inválido.')
    if not qr and not pairing and result.get('status') != 'connected':
        raise HTTPException(502, 'Nenhum código recebido. Atualize o estado e tente gerar novamente.')
    return {'qr': qr, 'pairing_code': pairing, 'expires_in': 20 if qr else 60, 'status': result.get('status')}

@router.get('/connection')
async def connection():
    value = settings.load(); name, token = selected(value)
    items = await instances(token, name)
    item = next((i for i in items if i.get('name') == name), None)
    if not item: raise HTTPException(404, 'Instância selecionada não encontrada.')
    return {'instance': public_instance(item)}

def hook_identity(value):
    deployment = infrastructure.load()
    return value.get('hook_label', deployment['webhook_label']), value.get('hook_url', deployment['webhook_url'])


async def read_hooks(value):
    name, token = selected(value)
    result = await upstream(token, 'GET', f'/api/events/getWebhook/{name}')
    hooks = result.get('webhooks')
    if not isinstance(hooks, list) or any(not isinstance(h, dict) or not isinstance(h.get('enabled'), bool)
                                          or not h.get('label') for h in hooks):
        raise HTTPException(502, 'A RyzeAPI não confirmou a lista de webhooks.')
    return hooks


async def verify_hook(value, enabled):
    label, url = hook_identity(value)
    hooks = await read_hooks(value)
    hook = next((h for h in hooks if h['label'] == label), {})
    if not enabled and not hook.get('enabled'):
        return
    if enabled and confirmed(dict(value, hook_label=label, hook_url=url), hooks):
        return
    raise HTTPException(502, 'Estado do webhook não confirmado. Confira a instância antes de continuar.')


async def disable_hook(value):
    # Keep credentials and the pending flag through uncertain writes, including process death.
    if not (value.get('webhook_configured') or value.get('hook_pending')):
        return
    label, _ = hook_identity(value)
    name, token = selected(value)
    value['hook_pending'] = True
    settings.save(value)
    own = next((h for h in await read_hooks(value) if h['label'] == label), {})
    if own.get('enabled'):
        if not owned_hook(value, own, label, hook_identity(value)[1]):
            raise HTTPException(409, 'O webhook pertence a outro receptor. A configuração remota foi preservada.')
        try:
            await upstream(token, 'POST', f'/api/events/webhook/{name}',
                           payload={'label': label, 'enabled': False})
        except HTTPException:
            # A timeout after commit and a failed write look identical until readback.
            pass
        await verify_hook(value, enabled=False)
    value.update(hook_pending=False, webhook_configured=False)
    settings.save(value)


async def apply_settings(value):
    if await restart() is False:
        return await runtime(value)
    for _ in range(16):
        if await runtime(value):
            return True
        await asyncio.sleep(0.5)
    raise HTTPException(503, 'O gateway não confirmou a configuração do canal.')


@router.post('/activate')
async def activate(request: Request):
    data = await body(request)
    deployment = infrastructure.load()
    label = deployment['webhook_label']
    url = deployment['webhook_url']
    if not url:
        raise HTTPException(400, 'Configure o endereço HTTPS para receber eventos.')
    async with mutation():
        value = settings.load()
        name, token = selected(value)
        if data.get('instance', name) != name:
            raise HTTPException(409, 'A instância mudou. Reabra as configurações antes de ativar.')
        permissions = firewall_fields(data)
        if data.get('use_saved') and (permissions['allowed_users'] != value.get('allowed_users') or
                                      permissions['allowed_recipients'] != settings.recipient_list(value)):
            raise HTTPException(409, 'As permissões mudaram. Reabra as configurações antes de ativar.')
        if value.get('enabled') or value.get('hook_pending'):
            raise HTTPException(409, 'Pause e reconcilie o canal antes de reativar.')
        item = next((i for i in await instances(token, name) if i.get('name') == name), None)
        if not item or public_instance(item)['status'] != 'connected':
            raise HTTPException(409, 'Conecte o WhatsApp antes de ativar o Hermes.')
        hooks = await read_hooks(value)
        for hook in hooks:
            if hook['enabled'] and not owned_hook(value, hook, label, url):
                raise HTTPException(409, 'Já existe um receptor ativo nesta instância. Escolha uma instância dedicada.')
            if hook['label'] == label and not hook['enabled'] and (
                    value.get('hook_label') != label or value.get('hook_instance') != name):
                raise HTTPException(409, 'Esse label já está reservado. Configure um label exclusivo.')
        if (settings.directory() / 'groups.db').exists():
            with GroupStore(settings.directory(), name) as store:
                groups_enabled = store.permitted_count() > 0
            if groups_enabled:
                await enable_group_events(token, name)
        value.update(**permissions, enabled=False, hook_pending=True, hook_url=url, hook_label=label, hook_instance=name,
                     webhook_secret=value.get('webhook_secret') or secrets.token_urlsafe(48))
        settings.save(value)
        try:
            await upstream(token, 'POST', f'/api/events/webhook/{name}', payload={
                'label': label, 'enabled': True, 'url': url,
                'authorization': 'Bearer '+value['webhook_secret'], 'events': EVENTS,
                'mediaBase64': True, 'byEvents': False})
            await verify_hook(value, enabled=True)
            value.update(enabled=True, webhook_configured=True, hook_pending=False)
            settings.save(value)
            running = await apply_settings(value)
        except Exception:
            value['enabled'] = False
            settings.save(value)
            await disable_hook(value)
            raise
    return {'enabled': True, 'runtime_running': running, 'redeploy_required': not running, 'webhook_configured': True}


@router.post('/firewall')
async def firewall(request: Request):
    data = await body(request)
    async with mutation():
        value = settings.load()
        name, _ = selected(value)
        if data.get('instance', name) != name:
            raise HTTPException(409, 'A instância mudou. Reabra as configurações antes de salvar.')
        permissions = firewall_fields(data, paused=not value.get('enabled'))
        value.update(permissions)
        settings.save(value)
        running = False
        if value.get('enabled'):
            try:
                running = await apply_settings(value)
            except Exception:
                value['enabled'] = False
                settings.save(value)
                await disable_hook(value)
                raise
    return {'saved': True, 'enabled': bool(value.get('enabled')),
            'redeploy_required': bool(value.get('enabled') and not running), **permissions}


@router.post('/pause')
async def pause(request: Request):
    await body(request)
    async with mutation():
        value = settings.load()
        value['enabled'] = False
        settings.save(value)
        await disable_hook(value)
        await restart()
    return {'enabled': False, 'webhook_configured': False}


@router.post('/forget')
async def forget(request: Request):
    data = await body(request)
    if data.get('confirm') is not True: raise HTTPException(400, 'Confirme a remoção local do acesso.')
    async with mutation():
        value = settings.load(); editable(value)
        settings.save({'enabled': False})
    return {'credential_saved': False}
