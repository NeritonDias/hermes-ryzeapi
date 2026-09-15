"""Dashboard control plane. Only allowlisted data is ever returned to the browser."""
import asyncio, base64, hashlib, hmac, os, re, secrets, time, shutil
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

BASE = 'https://ryzeapi.cloud'
PUBLIC_ORIGIN = infrastructure.load()['public_origin']
WEBHOOK_URL = infrastructure.load()['webhook_url']
LABEL = infrastructure.load()['webhook_label']
mutation_lock = asyncio.Lock()
upstream_clients = None

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
    if request.method != 'GET':
        if request.headers.get('origin') != PUBLIC_ORIGIN or request.headers.get('x-ryze-ui') != '1':
            raise HTTPException(403, 'Abra esta configuração pelo painel Hermes autenticado.')
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Envie os dados em JSON.')

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
    if value.get('enabled'): raise HTTPException(409, 'Pause o Hermes neste canal antes de trocar conta ou instância.')

def selected(value):
    if not value.get('instance') or not value.get('instance_token'):
        raise HTTPException(409, 'Selecione uma instância primeiro.')
    return valid_name(value['instance']), credential(value['instance_token'])

def firewall_fields(data):
    raw = text(data, 'allowed_users', 300)
    outbound = text(data, 'allowed_recipients', 1000) if 'allowed_recipients' in data else raw
    try:
        numbers, recipients = allowed_numbers(raw), allowed_numbers(outbound)
    except ValueError:
        raise HTTPException(400, 'Informe números com DDI/DDD, separados por vírgula. Listas vazias e liberação para todos não são permitidas.') from None
    if not all(authorized_phone(number, recipients) for number in numbers):
        raise HTTPException(400, 'Inclua os números que comandam o Hermes também na lista de quem pode receber respostas.')
    if data.get('confirm') is not True:
        raise HTTPException(400, 'Confirme as permissões do firewall de contatos.')
    return {'allowed_users': ','.join(sorted(numbers)), 'allowed_recipients': ','.join(sorted(recipients))}

async def runtime(value):
    if not value.get('webhook_secret'): return False
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            result = await client.get(infrastructure.health_url(), headers={'Authorization': 'Bearer '+value['webhook_secret']})
        data = result.json()
        return result.status_code == 200 and data.get('running') is True and data.get('instance') == value.get('instance')
    except (httpx.HTTPError, ValueError): return False

async def restart():
    if not shutil.which('systemctl'):
        raise HTTPException(503,'Esta beta requer Linux com um serviço systemd de usuário para o gateway. Consulte docs/INSTALL.md.')
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
    return {'credential_saved': bool(value.get('account_token')), 'credential_kind': value.get('credential_kind', 'account'),
            'instance': value.get('instance', ''), 'allowed_users': value.get('allowed_users', ''),
            'allowed_recipients': settings.recipient_list(value),
            'buffer_seconds': settings.buffer_seconds(value),
            'echo_transcripts': settings.echo_transcripts(value),
            'enabled': bool(value.get('enabled')), 'runtime_running': await runtime(value),
            'webhook_configured': bool(value.get('webhook_configured')), 'webhook_url': WEBHOOK_URL}

@router.get('/transport')
async def transport_health():
    value = settings.load()
    if not value.get('webhook_secret'): return {'running': False, 'websocket_connected': False}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            response = await client.get(infrastructure.health_url(),
                headers={'Authorization': 'Bearer '+value['webhook_secret']})
        if response.status_code != 200: raise ValueError('Not healthy')
        data = response.json()
        return {k: data.get(k) for k in ('running', 'websocket_connected', 'websocket_reconnects',
            'transport', 'last_event_at', 'last_send_at', 'counters', 'buffer_seconds', 'buffer_pending', 'echo_transcripts',
            'consumer_healthy', 'consumer_error', 'queue_counts', 'oldest_pending_seconds',
            'active_batches', 'pending_ttl_seconds', 'stt_busy', 'stt_waiting', 'orphaned_preparations',
            'ws_ingress_pending','ws_ingress_bytes','timings','early_receipts_pending','native_activity','maintenance_active',
            'whatsapp_state', 'whatsapp_observed_at', 'delivery_counts', 'review_items')}
    except (httpx.HTTPError, ValueError):
        return {'running': False, 'websocket_connected': False}

@router.get('/groups')
async def list_groups():
    value = settings.load(); name, _ = selected(value)
    with GroupStore(settings.directory(),name) as store:
        return {'instance':name,'groups':store.list()}

@router.post('/groups/sync')
async def sync_groups(request: Request):
    await body(request)
    async with mutation_lock:
        value = settings.load(); name, token = selected(value)
        result = await upstream(token,'GET',f'/api/group/list/{name}',params={'includeMembers':'false'},timeout=65)
        try:
            with GroupStore(settings.directory(),name) as store:
                groups = store.sync(result.get('groups'))
        except ValueError: raise HTTPException(502,'Lista de grupos inválida. O catálogo anterior foi preservado.') from None
    return {'instance':name,'groups':groups}

@router.post('/groups/policy')
async def group_policy(request: Request):
    data = await body(request)
    jid, mode, trigger, senders = (text(data,k) for k in ('jid','mode','trigger','senders'))
    if not group_id(jid) or mode not in {'blocked','listen','respond'} or trigger not in {'mentions','all'} or senders not in {'authorized','all'}:
        raise HTTPException(400,'Escolha um grupo e permissões válidas.')
    if data.get('confirm') is not True: raise HTTPException(400,'Confirme as permissões deste grupo.')
    async with mutation_lock:
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
                result = await upstream(token,'POST',f'/api/instance/settings/{name}',payload={'ignoreGroupMessages':False})
                # Ryze uses distinct routes for writing and reading settings.
                readback = await upstream(token,'GET',f'/api/instance/getSettings/{name}')
                if (readback.get('settings') or {}).get('ignoreGroupMessages') is not False:
                    raise HTTPException(502,'A RyzeAPI não confirmou o recebimento de grupos. Permissão não aplicada.')
                if value.get('webhook_configured'):
                    await upstream(token,'POST',f'/api/events/webhook/{name}',payload={
                        'label':LABEL,'enabled':True,'url':WEBHOOK_URL,'authorization':'Bearer '+value['webhook_secret'],
                        'events':EVENTS,'mediaBase64':True,'byEvents':False})
                    hook = (await upstream(token,'GET',f'/api/events/getWebhook/{name}',params={'label':LABEL})).get('webhook') or {}
                    if hook.get('events')!=EVENTS: raise HTTPException(502,'Eventos de grupo não confirmados no webhook.')
                store.configure(jid,mode,trigger,senders)
            groups=store.list()
    return {'saved':True,'instance':name,'groups':groups}

@router.post('/buffer')
async def save_buffer(request: Request):
    data = await body(request)
    seconds = data.get('buffer_seconds')
    if type(seconds) is not int or not 0 <= seconds <= 60:
        raise HTTPException(400, 'Informe um número inteiro de 0 a 60 segundos. Use 0 para responder sem espera.')
    async with mutation_lock:
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
    async with mutation_lock:
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
    async with mutation_lock:
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
    async with mutation_lock:
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
    async with mutation_lock:
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
    async with mutation_lock:
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

@router.post('/activate')
async def activate(request: Request):
    data = await body(request)
    permissions = firewall_fields(data)
    if not WEBHOOK_URL:
        raise HTTPException(400,'Configure seu webhook HTTPS com scripts/configure.py e reinicie o dashboard antes de ativar. Consulte docs/INSTALL.md.')
    async with mutation_lock:
        value = settings.load(); name, token = selected(value)
        items = await instances(token, name)
        item = next((i for i in items if i.get('name') == name), None)
        if not item or public_instance(item)['status'] != 'connected':
            raise HTTPException(409, 'Conecte o WhatsApp antes de ativar o Hermes.')
        value.update(**permissions, enabled=True,
                     webhook_secret=value.get('webhook_secret') or secrets.token_urlsafe(48), webhook_configured=False)
        settings.save(value)
        try:
            await restart()
            running = False
            for _ in range(16):
                if await runtime(value): running = True; break
                await asyncio.sleep(0.5)
            if not running: raise HTTPException(503, 'O canal RyzeAPI não iniciou no gateway. A ativação foi cancelada.')
            await upstream(token, 'POST', f'/api/events/webhook/{quote(name, safe="")}', payload={
                'label': LABEL, 'enabled': True, 'url': WEBHOOK_URL,
                'authorization': 'Bearer '+value['webhook_secret'], 'events': EVENTS,
                'mediaBase64': True, 'byEvents': False})
            readback = await upstream(token, 'GET', f'/api/events/getWebhook/{quote(name, safe="")}', params={'label': LABEL})
            hook = readback.get('webhook') or {}
            if not (hook.get('enabled') is True and hook.get('url') == WEBHOOK_URL and
                    hook.get('mediaBase64') is True and hook.get('byEvents') is False and
                    hook.get('events') == EVENTS and
                    hmac.compare_digest(str(hook.get('authorization', '')), 'Bearer '+value['webhook_secret'])):
                raise HTTPException(502, 'A RyzeAPI não confirmou o webhook esperado. Ativação cancelada; confira a configuração.')
            value['webhook_configured'] = True; settings.save(value)
        except Exception:
            value['enabled'] = False; settings.save(value)
            try: await restart()
            except Exception: pass  # Adapter independently checks the saved kill switch.
            raise
    return {'enabled': True, 'runtime_running': True, 'webhook_configured': True}

@router.post('/firewall')
async def firewall(request: Request):
    permissions = firewall_fields(await body(request))
    async with mutation_lock:
        value = settings.load(); selected(value)
        value.update(permissions); settings.save(value)
        if value.get('enabled'):
            try:
                await restart()
                for _ in range(16):
                    if await runtime(value): break
                    await asyncio.sleep(0.5)
                else: raise HTTPException(503, 'O gateway não confirmou o novo firewall. O canal foi pausado por segurança.')
            except Exception:
                value['enabled'] = False; settings.save(value)
                try: await restart()
                except Exception: pass
                raise
    return {'saved': True, 'enabled': bool(value.get('enabled')), **permissions}

@router.post('/pause')
async def pause(request: Request):
    await body(request)
    async with mutation_lock:
        value = settings.load(); value['enabled'] = False; settings.save(value)
        await restart()
    return {'enabled': False}

@router.post('/forget')
async def forget(request: Request):
    data = await body(request)
    if data.get('confirm') is not True: raise HTTPException(400, 'Confirme a remoção local do acesso.')
    async with mutation_lock:
        value = settings.load(); editable(value)
        settings.save({'enabled': False})
    return {'credential_saved': False}
