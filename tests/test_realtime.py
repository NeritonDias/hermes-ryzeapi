"""Real-transport regressions; synthetic credentials and events only."""
import asyncio, base64, copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import test_ryzeapi as original
from test_ryzeapi import event, OWNER
from ryzeapi.core import authorized_phone, phone_aliases, normalize
from ryzeapi.client import RyzeClient, RyzeError
import httpx

class IdentityTests(unittest.TestCase):
    def test_live_ryze_envelope_not_catalog_shape(self):
        value=event();msg=value['data']['message']
        value['data']={k:msg[k] for k in ('id','direction','timestamp','chat','sender')}
        value['data']['message']={'type':'text','content':'Oi','source':'','isEdit':False,
            'media':None,'context':None,'edit':None}
        item=normalize(value,instance='hermes-test',allowed={OWNER})
        self.assertEqual(item['text'],'Oi');self.assertEqual(item['number'],OWNER)
        value['data']['message']['direction']='incoming'
        value['data']['direction']='outgoing'
        self.assertIsNone(normalize(value,instance='hermes-test',allowed={OWNER}))

    def test_live_media_and_edits(self):
        value=event();msg=value['data']['message']
        value['data']={k:msg[k] for k in ('id','direction','timestamp','chat','sender')}
        value['data']['message']={'type':'audio','content':'','media':{
            'mimeType':'audio/ogg','base64':base64.b64encode(b'OggSfixture').decode()}}
        self.assertEqual(normalize(value,instance='hermes-test',allowed={OWNER})['media']['kind'],'audio')
        value['data']['message']['media']['isVoiceNote']=True
        self.assertEqual(normalize(value,instance='hermes-test',allowed={OWNER})['media']['kind'],'ptt')
        value['data']['message']['isEdit']=True
        self.assertIsNone(normalize(value,instance='hermes-test',allowed={OWNER}))

    def test_owner_ninth_digit_both_directions(self):
        self.assertEqual(phone_aliases('5511987654321'), {'5511987654321','551187654321'})
        self.assertEqual(authorized_phone('551187654321@s.whatsapp.net', {'5511987654321'}), '5511987654321')
        self.assertEqual(authorized_phone('5511987654321', {'551187654321'}), '551187654321')

    def test_not_foreign_landline_or_lid(self):
        for number in ('15551234567','551123456789','550112345678'):
            self.assertEqual(phone_aliases(number), {number})
        self.assertFalse(phone_aliases('123456789012345@lid'))
        self.assertFalse(authorized_phone('551187654322', {'5511987654321'}))

    def test_same_principal_and_authenticated_lid(self):
        value = event(); msg = value['data']['message']
        msg['sender'] = {'jid':'551187654321@s.whatsapp.net','lid':'123456789012345@lid'}
        msg['chat'] = {'jid':'123456789012345@lid','type':'private'}
        item = normalize(value, instance='hermes-test', allowed={'5511987654321'})
        self.assertEqual(item['number'], '5511987654321')
        self.assertEqual(item['transport_number'], '551187654321')
        msg['chat']['jid'] = '123456789@lid'
        self.assertIsNone(normalize(value, instance='hermes-test', allowed={'5511987654321'}))
        msg['sender']['jid'] = '123456789012345@lid'
        self.assertIsNone(normalize(value, instance='hermes-test', allowed={'5511987654321'}))

    def test_documents_video_sticker_and_reply(self):
        for kind,mime,name,raw in [('document','text/plain','../note.txt',b'hello'),
            ('document','application/vnd.openxmlformats-officedocument.wordprocessingml.document','note.docx',b'PKfixture'),
            ('video','video/mp4','clip.mp4',b'fixture'),('sticker','image/webp','sticker.webp',b'RIFFfixture')]:
            value=event(); msg=value['data']['message']
            msg['media']={'type':kind,'mimetype':mime,'fileName':name,'base64':base64.b64encode(raw).decode()}
            msg['reply']={'message_id':'quote','text':'context'}
            item=normalize(value,instance='hermes-test',allowed={OWNER})
            self.assertEqual(item['media']['kind'],kind)
            self.assertNotIn('/',item['media']['filename'])
            self.assertEqual(item['reply_id'],'quote')

class RealtimeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = original.AdapterTests.asyncSetUp
    asyncTearDown = original.AdapterTests.asyncTearDown
    async def test_two_transports_one_admission(self):
        results=await asyncio.gather(self.adapter.ingest(event(),'websocket'), self.adapter.ingest(event(),'webhook'))
        self.assertEqual(sorted(results),['duplicate','queued'])
        self.assertEqual(self.adapter.inbox.db.execute('select count(*) from inbox').fetchone()[0],1)

    async def test_voice_note_is_transcribed_inline_without_second_native_stt(self):
        from gateway.run import _event_media_is_stt_input
        received=[]
        async def handle(e):
            received.append(e);e._gateway_accepted=True;self.adapter._running=False
        self.adapter.handle_message=handle
        value=event();msg=value['data']['message']
        value['data']={k:msg[k] for k in ('id','direction','timestamp','chat','sender')}
        value['data']['message']={'type':'audio','content':'','media':{
            'mimetype':'audio/mpeg','isVoiceNote':True,'base64':base64.b64encode(b'ID3fixture').decode()}}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
        self.adapter._running=True
        with patch('ryzeapi.adapter.get_hermes_home',return_value=Path(self.temp.name)):
            await asyncio.wait_for(self.adapter.consume(),timeout=2)
        self.adapter.transcribe_voice.assert_awaited_once()
        self.assertIn('Transcrição sintética',received[0].text)
        self.assertEqual(received[0].media_urls,[])
        self.assertFalse(_event_media_is_stt_input(received[0],0))

    async def test_provider_resolves_lid_not_display_name(self):
        self.adapter.client=AsyncMock()
        self.adapter.client.contact.return_value={'found':True,'jid':OWNER+'@s.whatsapp.net','lid':'123456789@lid'}
        value=event();msg=value['data']['message']
        msg['sender']={'jid':'123456789:57@lid','name':'untrusted'}
        msg['chat']['jid']='123456789@lid'
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
        self.adapter.client.contact.assert_awaited_once_with('123456789@lid')

    async def test_unresolved_or_mismatched_lid_never_authorized(self):
        self.adapter.client=AsyncMock()
        self.adapter.client.contact.return_value={'found':True,'jid':OWNER,'lid':'999999999@lid','push_name':'Usuário'}
        value=event();msg=value['data']['message']
        msg['sender']={'jid':'123456789@lid'};msg['chat']['jid']='123456789@lid'
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'ignored')
        self.assertIsNone(self.adapter.inbox.take())

    async def test_missing_media_fetches_fixed_provider_after_authorization(self):
        self.adapter.client=AsyncMock()
        self.adapter.client.media_base64.return_value={'message_id':'test-message','base64':base64.b64encode(b'OggSfixture').decode()}
        value=event();value['data']['message']['media']={'type':'ptt','mimetype':'audio/ogg','url':'http://169.254.169.254'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
        self.adapter.client.media_base64.assert_not_awaited()
        with patch('ryzeapi.adapter.get_hermes_home',return_value=Path(self.temp.name)):
            await self.adapter.prepare_batch([self.adapter.inbox.take()])
        self.adapter.client.media_base64.assert_awaited_once_with('test-message')
        value['data']['message']['id']='other';value['data']['message']['sender']['jid']='5511888888888'
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'ignored')
        self.assertEqual(self.adapter.client.media_base64.await_count,1)

    async def test_webhook_fallback_when_websocket_down(self):
        self.adapter.ws_connected=False
        self.assertEqual(await self.adapter.ingest(event(),'webhook'),'queued')
        self.assertEqual(self.adapter.stats['webhook_queued'],1)

    async def test_media_failure_is_durable_with_explicit_unavailable_notice(self):
        self.adapter.client=AsyncMock();self.adapter.client.media_base64.side_effect=RyzeError('unavailable')
        value=event();value['data']['message']['media']={'type':'ptt','mimetype':'audio/ogg'}
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'queued')
        with patch('ryzeapi.adapter.asyncio.sleep',new=AsyncMock()):
            result,_ = await self.adapter.prepare_batch([self.adapter.inbox.take()])
        self.assertIn('Peça o reenvio',result.text)
        self.assertEqual(self.adapter.client.media_base64.await_count,3)

    async def test_send_media_firewall_and_native_attachment(self):
        self.adapter.client=AsyncMock();self.adapter.client.send_media.return_value='media-id'
        path=Path(self.temp.name)/'note.txt';path.write_text('fixture')
        self.assertFalse((await self.adapter.send_document('5511888888888',str(path))).success)
        self.adapter.client.send_media.assert_not_awaited()
        self.assertTrue((await self.adapter.send_document(OWNER,str(path))).success)
        args=self.adapter.client.send_media.call_args.args
        self.assertEqual(args[0],OWNER);self.assertEqual(args[2],'document')
        self.assertEqual(base64.b64decode(args[1]),b'fixture')

    async def test_native_gateway_does_not_retry_ambiguous_send(self):
        from gateway.platforms.base import SendResult
        self.adapter.send=AsyncMock(return_value=SendResult(success=False,error='RyzeAPI timeout; delivery uncertain'))
        result=await self.adapter._send_with_retry(OWNER,'fixture',reply_to=None,metadata=None)
        self.assertFalse(result.success)
        self.assertEqual(self.adapter.send.await_count,1)

    async def test_websocket_reconnects_and_stops_without_exposing_secret(self):
        self.adapter._running=True;self.adapter.client=AsyncMock()
        self.adapter.client.ensure_websocket.side_effect=RyzeError('secret-not-logged')
        async def sleep(_): self.adapter._running=False
        with patch('ryzeapi.adapter.asyncio.sleep',side_effect=sleep),self.assertLogs('ryzeapi.adapter',level='WARNING') as logs:
            await self.adapter.websocket_loop()
        self.assertEqual(self.adapter.ws_reconnects,1)
        self.assertFalse(self.adapter.ws_connected)
        self.assertNotIn('secret-not-logged',' '.join(logs.output))

    async def test_real_websocket_frames_and_reconnect(self):
        from ryzeapi.ingress import LaneQueue
        import aiohttp
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        count = 0
        self.adapter._running=True; self.adapter.token='synthetic-ws-token'
        self.adapter.client=AsyncMock()
        self.adapter.ws_ingress=LaneQueue(self.adapter.ingest_queued,lambda item:self.adapter.ingress_key(item[0]))
        self.adapter.ws_ingress.start()
        async def handler(request):
            nonlocal count
            self.assertEqual(request.headers['token'],'synthetic-ws-token')
            ws=web.WebSocketResponse();await ws.prepare(request)
            count += 1
            await ws.send_json(event())
            if count == 2:
                # Give the consumer time to process the duplicate before ending its loop.
                await asyncio.sleep(0.05)
                self.adapter._running=False
            await ws.close()
            return ws
        app=web.Application();app.router.add_get('/ws',handler)
        actual_session=aiohttp.ClientSession
        async with TestServer(app) as server:
            def session_factory(**kw):
                session=actual_session(**kw)
                connect=session.ws_connect
                session.ws_connect=lambda url,**kwargs: connect(server.make_url('/ws'),**kwargs)
                return session
            try:
                with patch('ryzeapi.adapter.aiohttp.ClientSession',side_effect=session_factory):
                    await asyncio.wait_for(self.adapter.websocket_loop(),timeout=5)
            finally: await self.adapter.ws_ingress.close()
        self.assertEqual(count,2)
        self.assertEqual(self.adapter.stats['websocket_queued'],1)
        self.assertEqual(self.adapter.stats['websocket_duplicate'],1)
        self.assertEqual(self.adapter.ws_reconnects,1)
        self.assertFalse(self.adapter.ws_connected)

class RealtimeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_configure_and_readback(self):
        seen=[]
        def handle(req):
            seen.append(req)
            return httpx.Response(200,json={'success':True,'websocket':{'enabled':True,'events':['message.exchange','instance.state','message.status','group.flow'],'mediaBase64':True}})
        client=RyzeClient('hermes-test','fixture',transport=httpx.MockTransport(handle))
        await client.ensure_websocket();await client.close()
        self.assertEqual([r.method for r in seen],['GET'])

    async def test_media_send_contract(self):
        def handle(req):
            p=json.loads(req.content)
            self.assertEqual(p['mediaType'],'document');self.assertEqual(p['number'],OWNER)
            self.assertIn('mediaBase64',p);self.assertNotIn('mediaUrl',p)
            return httpx.Response(200,json={'success':True,'data':{'messageId':'attachment'}})
        client=RyzeClient('hermes-test','fixture',transport=httpx.MockTransport(handle))
        self.assertEqual(await client.send_media(OWNER,'YWJj','document','text/plain','note.txt'),'attachment')
        await client.close()
