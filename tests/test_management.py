"""Isolated ASGI control-plane tests: no Ryze account or systemd mutations."""
import base64, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
if 'ryzeapi' not in sys.modules:
    spec = importlib.util.spec_from_file_location('ryzeapi', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec); sys.modules['ryzeapi'] = module; spec.loader.exec_module(module)
from ryzeapi import management as m, settings
OWNER = '5511999999999'
TOKEN = 'synthetic-account-secret'
INSTANCE_TOKEN = 'synthetic-instance-secret'
ITEM = {'name': 'hermes-test', 'token': INSTANCE_TOKEN, 'connection': {'state': 'connected', 'numberJid': OWNER},
        'integrations': {'chatwoot': {'apiToken': 'synthetic-other-secret'}}}
HEADERS = {'origin': m.PUBLIC_ORIGIN, 'x-ryze-ui': '1'}

class ManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.webhook_patch=patch.object(m,'WEBHOOK_URL','https://hooks.example.com/ryzeapi/events');self.webhook_patch.start()
        self.home = patch.object(settings, 'get_hermes_home', return_value=Path(self.temp.name)); self.home.start()
        settings.save({'enabled': False})
        app = FastAPI(); app.include_router(m.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=m.PUBLIC_ORIGIN, headers=HEADERS)
        self.calls = []
        self.hook = {}
        async def upstream(token, method, path, **kwargs):
            self.calls.append((token, method, path, kwargs))
            if path == '/api/instance/list': return {'success': True, 'instances': [ITEM]}
            if path.startswith('/api/instance/connect/'): return {'success': True, 'status': 'qr', 'qrCodeBase64': 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()}
            if path.startswith('/api/events/webhook/'):
                self.hook = kwargs['payload']; return {'success': True}
            if path.startswith('/api/events/getWebhook/'): return {'success': True, 'webhook': self.hook}
            if path == '/api/instance/new': return {'success': True, 'instance': dict(ITEM, name=kwargs['payload']['name'])}
            raise AssertionError('Unexpected upstream path')
        self.up = patch.object(m, 'upstream', side_effect=upstream); self.up.start()
        self.restart = patch.object(m, 'restart', new=AsyncMock()); self.restart_mock = self.restart.start()
        self.runtime = patch.object(m, 'runtime', new=AsyncMock(return_value=True)); self.runtime_mock = self.runtime.start()

    async def asyncTearDown(self):
        await self.client.aclose(); self.up.stop(); self.restart.stop(); self.runtime.stop(); self.home.stop(); self.webhook_patch.stop(); self.temp.cleanup()

    async def setup_selected(self):
        self.assertEqual((await self.client.post('/account', json={'token': TOKEN, 'kind': 'account'})).status_code, 200)
        self.assertEqual((await self.client.post('/select', json={'name': ITEM['name']})).status_code, 200)

    async def test_transcription_toggle_strict_persistent_and_no_restart(self):
        await self.setup_selected()
        value=settings.load();value['buffer_seconds']=20;settings.save(value)
        self.assertTrue((await self.client.get('/state')).json()['echo_transcripts'])
        for setting in (False,True):
            response=await self.client.post('/transcription',json={'echo_transcripts':setting})
            self.assertEqual(response.status_code,200)
            self.assertIs(settings.load()['echo_transcripts'],setting)
            self.assertIs((await self.client.get('/state')).json()['echo_transcripts'],setting)
            self.assertEqual(settings.load()['buffer_seconds'],20)
        for bad in ('false',0,1,None,[]):
            self.assertEqual((await self.client.post('/transcription',json={'echo_transcripts':bad})).status_code,400)
        self.assertEqual((await self.client.post('/transcription',json={'echo_transcripts':False},headers={'origin':'https://evil.invalid'})).status_code,403)
        self.restart_mock.assert_not_awaited()

    async def test_account_whitelist_permissions_and_state(self):
        response = await self.client.post('/account', json={'token': TOKEN, 'kind': 'account'})
        self.assertEqual(response.status_code, 200)
        for secret in [TOKEN, INSTANCE_TOKEN, 'synthetic-other-secret']: self.assertNotIn(secret, response.text)
        state = await self.client.get('/state')
        self.assertNotIn(TOKEN, state.text); self.assertTrue(state.json()['credential_saved'])
        self.assertEqual(state.headers['cache-control'], 'no-store')
        self.assertEqual((Path(self.temp.name)/'ryzeapi/settings.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual((Path(self.temp.name)/'ryzeapi').stat().st_mode & 0o777, 0o700)

    async def test_csrf_and_invalid_bodies(self):
        for origin in ['https://evil.invalid', 'null', '']:
            response = await self.client.post('/account', json={'token': TOKEN}, headers={'origin': origin})
            self.assertEqual(response.status_code, 403); self.assertNotIn(TOKEN, response.text)
        self.assertEqual((await self.client.post('/account', json={}, headers={'x-ryze-ui': ''})).status_code,403)
        self.assertEqual((await self.client.post('/account', content='{}')).status_code,415)
        self.assertEqual((await self.client.post('/account', json={'token': 'x'*17000})).status_code,413)
        self.assertEqual((await self.client.post('/account', json={'token': {'secret': TOKEN}, 'kind': 'account'})).status_code,400)
        self.assertEqual(self.calls, [])

    async def test_selection_requires_membership(self):
        await self.setup_selected()
        response = await self.client.post('/select', json={'name': 'someone-else'})
        self.assertEqual(response.status_code,404)
        self.assertEqual(settings.load()['instance'], 'hermes-test')

    async def test_create_requires_explicit_confirmation_and_account(self):
        await self.setup_selected()
        self.assertEqual((await self.client.post('/instances', json={'name': 'new-one'})).status_code,400)
        self.assertEqual((await self.client.post('/instances', json={'name': 'hermes-test', 'confirm': True})).status_code,409)
        response = await self.client.post('/instances', json={'name': 'new-one', 'confirm': True})
        self.assertEqual(response.status_code,200)
        posts = [c for c in self.calls if c[2] == '/api/instance/new']
        self.assertEqual(len(posts),1)
        self.assertTrue(posts[0][3]['payload']['disableHistorySync'])
        value = settings.load(); value['credential_kind']='instance'; settings.save(value)
        self.assertEqual((await self.client.post('/instances', json={'name': 'another', 'confirm': True})).status_code,409)

    async def test_qr_and_connection_do_not_activate(self):
        await self.setup_selected()
        qr = await self.client.post('/connect', json={})
        self.assertEqual(qr.status_code,200); self.assertEqual(qr.json()['expires_in'],20)
        self.assertNotIn('qr', settings.load())
        self.assertFalse(settings.load()['enabled'])
        response = await self.client.get('/connection'); self.assertEqual(response.json()['instance']['status'],'connected')
        self.assertNotIn(INSTANCE_TOKEN,response.text)
        self.assertEqual((await self.client.post('/connect', json={'number': '*'})).status_code,400)

    async def test_real_api_raw_base64_shape_and_hostile_qr(self):
        await self.setup_selected()
        png=base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        with patch.object(m,'upstream',return_value={'status':'qr_code_generated','qrCodeBase64':png}):
            response=await self.client.post('/connect',json={})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['qr'],'data:image/png;base64,'+png)
        for qr in ['data:image/svg+xml;base64,PHN2Zz4=', 'https://evil.invalid/qr',base64.b64encode(b'<svg/>').decode()]:
            with patch.object(m,'upstream',return_value={'qrCodeBase64':qr}):
                self.assertEqual((await self.client.post('/connect',json={})).status_code,502)

    async def test_activate_pause_and_forget(self):
        await self.setup_selected()
        self.assertEqual((await self.client.post('/activate', json={'allowed_users': '*', 'confirm': True})).status_code,400)
        self.assertEqual((await self.client.post('/activate', json={'allowed_users': OWNER})).status_code,400)
        result = await self.client.post('/activate', json={'allowed_users': OWNER, 'confirm': True})
        self.assertEqual(result.status_code,200); self.assertTrue(settings.configured())
        self.assertNotIn(settings.load()['webhook_secret'], result.text)
        self.assertEqual((await self.client.post('/forget',json={'confirm':True})).status_code,409)
        self.assertEqual((await self.client.post('/account',json={'token': TOKEN,'kind':'account'})).status_code,409)
        self.assertEqual((await self.client.post('/pause',json={})).status_code,200)
        self.assertFalse(settings.configured())
        self.assertEqual((await self.client.post('/forget',json={'confirm':True})).status_code,200)
        self.assertNotIn('account_token', settings.load())

    async def test_activation_readback_failure_rolls_back(self):
        await self.setup_selected()
        async def broken(token, method, path, **kwargs):
            if path == '/api/instance/list': return {'instances':[ITEM]}
            return {'webhook': {}}
        with patch.object(m,'upstream',side_effect=broken):
            result = await self.client.post('/activate',json={'allowed_users':OWNER,'confirm':True})
        self.assertEqual(result.status_code,502)
        self.assertFalse(settings.load()['enabled']); self.assertEqual(self.restart_mock.await_count,2)

    async def test_firewall_saved_without_connecting_or_authorizing_recipient(self):
        await self.setup_selected()
        friend='5511888888888'
        result=await self.client.post('/firewall',json={'allowed_users':OWNER,'allowed_recipients':OWNER+','+friend,'confirm':True})
        self.assertEqual(result.status_code,200)
        value=settings.load()
        self.assertFalse(value['enabled'])
        self.assertEqual(value['allowed_users'],OWNER)
        self.assertIn(friend,value['allowed_recipients'])
        self.restart_mock.assert_not_awaited()
        self.assertEqual((await self.client.get('/state')).json()['allowed_recipients'],value['allowed_recipients'])
        for recipients in ['', '*', friend]:
            result=await self.client.post('/firewall',json={'allowed_users':OWNER,'allowed_recipients':recipients,'confirm':True})
            self.assertEqual(result.status_code,400)

    async def test_live_firewall_failure_pauses_channel(self):
        await self.setup_selected()
        value=settings.load();value.update(enabled=True,allowed_users=OWNER);settings.save(value)
        self.restart_mock.side_effect=HTTPException(503,'Restart unavailable')
        result=await self.client.post('/firewall',json={'allowed_users':OWNER,'allowed_recipients':OWNER,'confirm':True})
        self.assertEqual(result.status_code,503)
        self.assertFalse(settings.load()['enabled'])

    async def test_buffer_validation_persistence_without_restart(self):
        await self.setup_selected()
        before=settings.load()
        self.assertEqual((await self.client.get('/state')).json()['buffer_seconds'],10)
        for invalid in (-1,61,True,False,'10',1.5,None):
            response=await self.client.post('/buffer',json={'buffer_seconds':invalid})
            self.assertEqual(response.status_code,400)
        self.assertEqual(settings.load(),before)
        for seconds in (0,60,10):
            response=await self.client.post('/buffer',json={'buffer_seconds':seconds})
            self.assertEqual(response.status_code,200)
            self.assertEqual(settings.load(),dict(before,buffer_seconds=seconds))
            self.assertEqual((await self.client.get('/state')).json()['buffer_seconds'],seconds)
        self.restart_mock.assert_not_awaited()

    async def test_failed_restart_does_not_leave_enabled(self):
        await self.setup_selected()
        self.restart_mock.side_effect = HTTPException(503,'Gateway unavailable')
        self.assertEqual((await self.client.post('/activate',json={'allowed_users':OWNER,'confirm':True})).status_code,503)
        self.assertFalse(settings.load()['enabled'])

    async def test_native_registry_and_authorization_bridge(self):
        await self.setup_selected()
        value=settings.load(); value.update(enabled=True,allowed_users=OWNER); settings.save(value)
        class Context:
            def register_platform(self, **kwargs):
                from gateway.platform_registry import PlatformEntry, platform_registry
                self.entry=kwargs
                platform_registry.register(PlatformEntry(**kwargs))
        ctx=Context()
        with patch.dict(os.environ, {}, clear=False):
            sys.modules['ryzeapi'].register(ctx)
            self.assertEqual(os.environ['RYZEAPI_ALLOWED_USERS'],OWNER)
            self.assertEqual(ctx.entry['env_enablement_fn'](),{'allowed_users':OWNER})
            self.assertTrue(ctx.entry['is_connected'](None))
            from gateway.authz_mixin import GatewayAuthorizationMixin
            from gateway.config import Platform, PlatformConfig
            from gateway.session import SessionSource
            from ryzeapi.adapter import RyzeAdapter
            gate=GatewayAuthorizationMixin()
            gate.adapters={Platform('ryzeapi'):RyzeAdapter(PlatformConfig())}
            source=SessionSource(platform=Platform('ryzeapi'),chat_id=OWNER,user_id=OWNER,chat_type='dm')
            self.assertTrue(gate._principal_authorized(source,allow_adapter_delegation=True))
            source.user_id='5511888888888'; source.chat_id=source.user_id
            self.assertFalse(gate._principal_authorized(source,allow_adapter_delegation=True))

    async def test_upstream_transport_redacts_and_does_not_retry(self):
        # Exercise real HTTP client through MockTransport, not the route stub.
        self.up.stop()
        original=httpx.AsyncClient
        calls=[]
        def transport(request):
            calls.append(request)
            self.assertEqual(request.headers['token'],TOKEN)
            return httpx.Response(401,json={'error':TOKEN})
        with patch.object(m.httpx,'AsyncClient',side_effect=lambda **kw: original(**{**kw,'transport':httpx.MockTransport(transport)})):
            with self.assertRaises(HTTPException) as caught: await m.upstream(TOKEN,'POST','/api/instance/new',payload={'name':'test'})
        self.assertNotIn(TOKEN,str(caught.exception.detail)); self.assertEqual(len(calls),1)
        self.assertEqual(caught.exception.status_code,400)

if __name__ == '__main__': unittest.main(verbosity=2)
