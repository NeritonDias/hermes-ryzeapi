"""0.8 fault combinations and receipts: synthetic fixtures only."""
import asyncio,base64,json,sqlite3,time,threading,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import AsyncMock,patch
import test_ryzeapi as original
from test_ryzeapi import norm,event,OWNER
from ryzeapi.telemetry import Telemetry

class MonitoringTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=original.AdapterTests.asyncSetUp
    asyncTearDown=original.AdapterTests.asyncTearDown
    def put(self,mid,text='fixture',audio=False):
        item=norm(event());item.update(id=mid,text=text)
        if audio:item['media']={'kind':'ptt','mime':'audio/ogg','base64':base64.b64encode(b'OggSfixture').decode()}
        self.adapter.inbox.put(item);return item
    async def start(self):
        self.adapter._running=True;self.adapter.last_housekeeping=time.monotonic()
        self.adapter.worker=asyncio.create_task(self.adapter.consume())
    async def stop(self):
        self.adapter.worker.cancel();await asyncio.gather(self.adapter.worker,return_exceptions=True)
    async def test_atomic_stop_failure_rolls_back_and_recovers(self):
        entered=asyncio.Event();stopped=asyncio.Event();received=[]
        async def transcribe(path):entered.set();await asyncio.Event().wait()
        async def handle(e):received.append(e.text);e._gateway_accepted=True;stopped.set()
        self.adapter.transcribe_voice.side_effect=transcribe;self.adapter.handle_message=handle
        self.adapter.send_transcripts=AsyncMock()
        self.put('audio',audio=True)
        original_cancel=self.adapter.inbox._cancel_before_stop;failures=[]
        def cancel(stop):
            original_cancel(stop)
            if not failures:
                failures.append(True);raise sqlite3.OperationalError('synthetic fault after SQL update')
        with patch.object(self.adapter.inbox,'_cancel_before_stop',side_effect=cancel),patch('ryzeapi.adapter.get_hermes_home',return_value=Path(self.temp.name)):
            await self.start()
            try:
                await asyncio.wait_for(entered.wait(),2)
                self.put('stop','/stop')
                await asyncio.wait_for(stopped.wait(),3)
                self.assertEqual(received,['/stop'])
                self.assertEqual(self.adapter.inbox.db.execute("SELECT status FROM inbox WHERE id='audio'").fetchone()[0],'cancelled')
            finally:await self.stop()
    async def test_orphaned_stop_is_unhealthy_then_resumed_once(self):
        self.put('stop','/stop');self.adapter.inbox.take_batch(0,stops_only=True,claim='preparing')
        self.adapter._running=True;self.adapter.consumer_tick=time.monotonic()
        self.adapter.worker=asyncio.create_task(asyncio.sleep(3))
        class Request:headers={'Authorization':'Bearer '+'s'*40}
        health=json.loads((await self.adapter.health(Request())).body)
        self.assertFalse(health['consumer_healthy']);self.assertEqual(health['orphaned_preparations'],1)
        await self.stop()
        received=asyncio.Event()
        async def handle(e):e._gateway_accepted=True;received.set()
        self.adapter.handle_message=AsyncMock(side_effect=handle)
        await self.start()
        try:await asyncio.wait_for(received.wait(),2)
        finally:await self.stop()
        self.assertEqual(self.adapter.handle_message.await_count,1)
    async def test_cancelled_preparation_cannot_cross_handoff_or_be_revived(self):
        first=self.put('first');self.adapter.inbox.take_batch(0,claim='preparing')
        self.put('stop','/stop');self.adapter.inbox.take_batch(0,stops_only=True,claim='preparing')
        self.assertFalse(self.adapter.inbox.begin_handoff([first]))
        self.adapter.inbox.set_batch_status([first],'pending')
        self.assertEqual(self.adapter.inbox.db.execute("SELECT status FROM inbox WHERE id='first'").fetchone()[0],'cancelled')
    async def test_commands_are_fifo_except_stop(self):
        for mid,text in [('first','FIRST'),('command','/status'),('last','LAST')]:self.put(mid,text)
        self.assertEqual(self.adapter.inbox.take_batch(60)[0]['id'],'first')
        self.assertEqual(self.adapter.inbox.take_batch(60)[0]['id'],'command')
        self.assertEqual(self.adapter.inbox.take_batch(0)[0]['id'],'last')
    async def test_idle_expiration_never_parses_media_json(self):
        self.put('audio',audio=True)
        with patch('ryzeapi.core.json.loads',side_effect=AssertionError('payload scan during idle')):
            self.assertEqual(self.adapter.inbox.take_batch(0,stops_only=True),[])
            self.assertEqual(self.adapter.inbox.take_batch(60),[])
    async def test_media_reference_admission_does_not_wait_for_download(self):
        self.adapter.client=AsyncMock()
        audio=event();audio['data']['message']['media']={'type':'ptt','mimetype':'audio/ogg'}
        stop=event();stop['data']['message'].update(id='stop',content={'text':'/stop'})
        self.assertEqual(await asyncio.wait_for(self.adapter.ingest(audio,'websocket'),.5),'queued')
        self.assertEqual(await asyncio.wait_for(self.adapter.ingest(stop,'webhook'),.5),'queued')
        self.adapter.client.media_base64.assert_not_awaited()
        self.assertEqual(self.adapter.inbox.take_batch(0,stops_only=True)[0]['id'],'stop')
    async def test_stt_waits_its_turn_without_concurrent_inference(self):
        from ryzeapi.adapter import RyzeAdapter
        release=asyncio.Event();entered=asyncio.Event();calls=[]
        async def backend(path):
            calls.append(str(path))
            if len(calls)==1:entered.set();await release.wait()
            return str(path)
        with patch('ryzeapi.adapter.run_stt',side_effect=backend):
            one=asyncio.create_task(RyzeAdapter.transcribe_voice(self.adapter,Path('/first')))
            try:
                await asyncio.wait_for(entered.wait(),2)
                two=asyncio.create_task(RyzeAdapter.transcribe_voice(self.adapter,Path('/second')))
                await asyncio.sleep(.05);self.assertEqual(calls,['/first']);self.assertFalse(two.done())
                release.set();self.assertEqual(await one,'/first');self.assertEqual(await two,'/second')
            finally:release.set();await asyncio.gather(one,return_exceptions=True)
    async def test_structured_messages_and_firewall(self):
        for field,value,expected in [('location',{'latitude':-16.6,'longitude':-49.2,'address':'Fixture'},'Localização'),
            ('contact',{'display_name':'Fixture','phone_number':OWNER},'Contato compartilhado'),
            ('button_response',{'title':'Aprovar','selected_button_id':'yes'},'Resposta de botão'),
            ('list_response',{'single_select_reply':{'option_name':'fixture'}},'Resposta de lista')]:
            payload=event();msg=payload['data']['message'];msg['content']={};msg[field]=value
            self.assertIn(expected,norm(payload)['text'])
            msg['sender']['jid']='5511888888888';self.assertIsNone(norm(payload))
    async def test_bad_location_and_contact_are_not_commands(self):
        payload=event();msg=payload['data']['message'];msg['content']={};msg['location']={'latitude':float('nan'),'longitude':0}
        self.assertIsNone(norm(payload))
        msg['contact']={'display_name':'/stop'}
        self.assertFalse(norm(payload)['text'].startswith('/'))

class ReceiptTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=original.AdapterTests.asyncSetUp
    asyncTearDown=original.AdapterTests.asyncTearDown
    def ledger(self):return Telemetry(self.adapter.inbox.db)
    def receipt(self,state='delivered',mid='sent'):
        return {'event':'message.status','instanceData':{'instance':'hermes-test','token':'DO-NOT-LEAK'},
            'data':{'timestamp':datetime.now(timezone.utc).isoformat(),'status':state,'messageIds':[mid],
                    'chat':{'jid':OWNER,'type':'private'},'recipient':OWNER}}
    async def test_receipts_correlate_only_known_authorized_sends(self):
        ledger=self.ledger();ledger.sent('sent',OWNER)
        self.assertTrue(ledger.event(self.receipt(),'hermes-test',{OWNER}))
        self.assertFalse(ledger.event(self.receipt(mid='unknown'),'hermes-test',{OWNER}))
        self.assertFalse(ledger.event(self.receipt(),'other-instance',{OWNER}))
        self.assertFalse(ledger.event(self.receipt(),'hermes-test',{'5511888888888'}))
        self.assertNotIn('DO-NOT-LEAK',json.dumps(ledger.summary()))
    async def test_duplicate_and_out_of_order_receipts_do_not_downgrade(self):
        ledger=self.ledger();ledger.sent('sent',OWNER)
        for state in ['read','delivered','read','server_error']:
            ledger.event(self.receipt(state),'hermes-test',{OWNER})
        self.assertEqual(ledger.summary()['delivery_counts'],{'read':1})
    async def test_receipt_state_survives_reopening_ledger(self):
        self.ledger().sent('sent',OWNER)
        self.assertEqual(self.ledger().summary()['delivery_counts'],{'accepted':1})
    async def test_unknown_or_stale_instance_state_is_not_connected(self):
        ledger=self.ledger();self.assertEqual(ledger.summary()['whatsapp_state'],'unknown')
        ledger.state('connected');ledger.state('disconnected',time.time()-10)
        self.assertEqual(ledger.summary()['whatsapp_state'],'connected')
        self.adapter.inbox.db.execute('UPDATE ryze_state SET observed=?',(time.time()-181,))
        self.assertEqual(ledger.summary()['whatsapp_state'],'unknown')
    async def test_state_events_never_go_to_agent(self):
        self.adapter.telemetry=self.ledger()
        payload={'event':'instance.state','instanceData':{'instance':'hermes-test'},'data':{
            'state':'connected','timestamp':datetime.now(timezone.utc).isoformat(),'codes':['SECRET-QR']}}
        self.assertEqual(await self.adapter.ingest(payload,'websocket'),'observed')
        self.assertEqual(self.adapter.inbox.db.execute('SELECT count(*) FROM inbox').fetchone()[0],0)
        self.assertNotIn('SECRET-QR',json.dumps(self.ledger().summary()))
