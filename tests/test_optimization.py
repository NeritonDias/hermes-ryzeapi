"""0.9 regressions: synthetic payloads, isolated DBs, disposable subprocesses."""
import asyncio,copy,json,os,signal,sys,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
import test_ryzeapi as original
from test_ryzeapi import event,norm,OWNER
from ryzeapi.core import normalize
from ryzeapi.telemetry import Telemetry
from ryzeapi.ingress import LaneQueue
from ryzeapi.timings import Timings
from ryzeapi.stt import run_stt
from ryzeapi.client import RyzeClient

class OptimizationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=original.AdapterTests.asyncSetUp
    asyncTearDown=original.AdapterTests.asyncTearDown

    def receipt(self,mid='sent',state='read',number=OWNER):
        return {'event':'message.status','instanceData':{'instance':'hermes-test'},'data':{
            'timestamp':datetime.now(timezone.utc).isoformat(),'status':state,'messageIds':[mid],
            'chat':{'type':'private','jid':number},'recipient':number}}

    def ledger(self):
        self.adapter.telemetry=Telemetry(self.adapter.inbox.db)
        return self.adapter.telemetry

    async def test_early_receipt_survives_restart_and_matches_send(self):
        t=self.ledger();t.event(self.receipt(),'hermes-test',{OWNER})
        self.assertEqual(t.summary()['delivery_counts'],{})
        self.assertEqual(t.summary()['early_receipts_pending'],1)
        t=Telemetry(self.adapter.inbox.db);t.sent('sent',OWNER)
        self.assertEqual(t.summary()['delivery_counts'],{'read':1})
        self.assertEqual(t.summary()['early_receipts_pending'],0)

    async def test_early_receipts_do_not_regress_or_authorize_other_sender(self):
        t=self.ledger()
        t.event(self.receipt(state='read'),'hermes-test',{OWNER})
        t.event(self.receipt(state='delivered'),'hermes-test',{OWNER})
        t.event(self.receipt(mid='other',number='5511888888888'),'hermes-test',{OWNER})
        t.sent('sent',OWNER);t.sent('other',OWNER)
        self.assertEqual(t.summary()['delivery_counts'],{'read':1,'accepted':1})

    async def test_early_receipt_ttl_and_cap(self):
        t=self.ledger()
        for start in range(0,1024,256):
            payload=self.receipt();payload['data']['messageIds']=[str(i) for i in range(start,start+256)]
            t.event(payload,'hermes-test',{OWNER})
        self.assertEqual(t.summary()['early_receipts_pending'],1000)
        with patch('ryzeapi.telemetry.time.time',return_value=time.time()+301):
            t.cleanup();self.assertEqual(t.summary()['early_receipts_pending'],0)

    async def test_snapshot_is_identity_bound_and_never_downgrades(self):
        t=self.ledger();t.sent('sent',OWNER)
        good={'message_id':'sent','direction':'sent','chat_jid':OWNER+'@s.whatsapp.net','status':'read'}
        for changes in ({'message_id':'wrong'},{'direction':'received'},{'chat_jid':'5511888888888'}):
            self.assertFalse(t.snapshot(dict(good,**changes),'sent',OWNER,{OWNER}))
        self.assertTrue(t.snapshot(good,'sent',OWNER,{OWNER}))
        self.assertFalse(t.snapshot(dict(good,status='delivered'),'sent',OWNER,{OWNER}))
        self.assertEqual(t.summary()['delivery_counts'],{'read':1})

    async def test_reconciliation_is_bounded_read_only_and_backed_off(self):
        t=self.ledger();self.adapter.client=AsyncMock()
        for i in range(7):t.sent(str(i),OWNER)
        with t.db:t.db.execute('UPDATE ryze_sent SET created=created-40')
        async def status(mid):return {'message_id':mid,'direction':'sent','chat_jid':OWNER,'status':'delivered'}
        self.adapter.client.message_status.side_effect=status
        await self.adapter.reconcile_once();self.assertEqual(self.adapter.client.message_status.await_count,5)
        await self.adapter.reconcile_once();self.assertEqual(self.adapter.client.message_status.await_count,7)
        await self.adapter.reconcile_once();self.assertEqual(self.adapter.client.message_status.await_count,7)
        self.adapter.client.send_text.assert_not_awaited();self.adapter.client.send_media.assert_not_awaited()

    async def test_malformed_state_event_is_ignored_not_retried(self):
        self.ledger()
        self.assertEqual(await self.adapter.ingest({'event':'message.status','instanceData':['bad']},'webhook'),'ignored')

    def mutation(self,target='original',text='corrected',revoke=False):
        payload=event();msg=payload['data']['message']
        msg['id']=target if revoke else 'edit-event'
        msg['timestamp']=datetime.now(timezone.utc).isoformat()
        msg['type']='message_revoke' if revoke else 'message_edit'
        if not revoke:msg['edit']={'original_id':target,'text':text}
        return payload

    def put_original(self,text='original'):
        item=norm(event());item.update(id='original',text=text)
        self.adapter.inbox.put(item)
        return item

    async def test_edit_preserves_position_and_duplicate_cannot_revert(self):
        self.put_original()
        created=self.adapter.inbox.db.execute('SELECT created FROM inbox').fetchone()[0]
        older=self.mutation(text='first correction');newer=self.mutation(text='latest correction')
        self.assertEqual(await self.adapter.ingest(newer,'websocket'),'edited')
        self.assertEqual(await self.adapter.ingest(older,'webhook'),'ignored')
        self.assertEqual(await self.adapter.ingest(newer,'webhook'),'ignored')
        row=self.adapter.inbox.db.execute('SELECT payload,created FROM inbox').fetchone()
        self.assertEqual(json.loads(row[0])['text'],'latest correction');self.assertEqual(row[1],created)
        self.assertEqual(self.adapter.inbox.db.execute('SELECT count(*) FROM inbox').fetchone()[0],1)

    async def test_revoke_scrubs_only_pending_target_and_stays_deduplicated(self):
        item=self.put_original()
        self.assertEqual(await self.adapter.ingest(self.mutation(revoke=True),'webhook'),'revoked')
        self.assertEqual(self.adapter.inbox.db.execute('SELECT status,payload FROM inbox').fetchone(),('cancelled','{}'))
        self.assertEqual(self.adapter.inbox.put(item),'duplicate')
        self.assertEqual(self.adapter.inbox.take_batch(0),[])

    async def test_edit_revoke_cannot_change_preparation_or_handoff(self):
        self.put_original();batch=self.adapter.inbox.take_batch(0,claim='preparing')
        self.assertEqual(await self.adapter.ingest(self.mutation(),'webhook'),'ignored')
        self.assertTrue(self.adapter.inbox.begin_handoff(batch))
        self.assertEqual(await self.adapter.ingest(self.mutation(revoke=True),'websocket'),'ignored')
        self.assertEqual(self.adapter.inbox.db.execute('SELECT status FROM inbox').fetchone()[0],'handoff')

    async def test_mutations_cannot_cross_firewall_or_create_commands(self):
        self.put_original()
        payload=self.mutation();payload['data']['message']['sender']['jid']='5511888888888'
        self.assertEqual(await self.adapter.ingest(payload,'webhook'),'ignored')
        self.assertEqual(await self.adapter.ingest(self.mutation(text='/stop'),'webhook'),'ignored')
        self.assertEqual(await self.adapter.ingest(self.mutation(target='missing'),'webhook'),'ignored')
        with self.adapter.inbox.db:self.adapter.inbox.db.execute('UPDATE inbox SET is_command=1')
        self.assertEqual(await self.adapter.ingest(self.mutation(),'webhook'),'ignored')

    async def test_live_edit_keeps_explicit_original_id(self):
        self.put_original();payload=self.mutation();msg=payload['data']['message']
        payload['data']={key:msg[key] for key in ('id','direction','timestamp','chat','sender')}
        payload['data']['message']={'type':'text','content':'corrected','isEdit':True,'edit':msg['edit']}
        self.assertEqual(await self.adapter.ingest(payload,'webhook'),'edited')

    async def test_edited_buffer_is_admitted_once_with_new_text(self):
        self.put_original();await self.adapter.ingest(self.mutation(),'webhook')
        received=[]
        async def handle(e):received.append(e.text);e._gateway_accepted=True
        self.adapter.handle_message=handle
        await self.adapter.process_batch(self.adapter.inbox.take_batch(0,claim='preparing'))
        self.assertEqual(received,['corrected']);self.assertEqual(self.adapter.inbox.take_batch(0),[])

    async def test_metrics_measure_stages_without_message_content(self):
        self.put_original();self.adapter.client=AsyncMock();self.adapter.client.send_text.return_value='sent'
        async def handle(e):
            e._gateway_accepted=True
            await self.adapter.send(OWNER,'private-content')
        self.adapter.handle_message=handle
        await self.adapter.process_batch(self.adapter.inbox.take_batch(0,claim='preparing'))
        data=self.adapter.timings.summary()
        for key in ('buffer','preparation','gateway_handoff','agent_to_first_send','send_text'):self.assertEqual(data[key]['count'],1)
        self.assertNotIn('private-content',json.dumps(data));self.assertNotIn(OWNER,json.dumps(data))

    async def test_shared_ingress_preserves_ws_webhook_order(self):
        release=asyncio.Event();entered=asyncio.Event();seen=[]
        original_resolve=self.adapter.resolve_sender
        async def resolve(payload):
            mid=payload['data']['message']['id']
            if mid=='one':entered.set();await release.wait()
            seen.append(mid);return await original_resolve(payload)
        self.adapter.resolve_sender=resolve
        q=LaneQueue(self.adapter.ingest_queued,lambda pair:self.adapter.ingress_key(pair[0]))
        one=event();one['data']['message']['id']='one'
        two=event();two['data']['message']['id']='two'
        q.start()
        try:
            first=asyncio.get_running_loop().create_future();second=asyncio.get_running_loop().create_future()
            q.put((one,'websocket'),100,first);await asyncio.wait_for(entered.wait(),1)
            q.put((two,'webhook'),100,second);await asyncio.sleep(.02)
            self.assertFalse(second.done());release.set()
            self.assertEqual(await first,'queued');self.assertEqual(await second,'queued');self.assertEqual(seen,['one','two'])
        finally:release.set();await q.close()

    async def test_arrival_order_survives_out_of_order_identity_completion(self):
        later=norm(event());later.update(id='later',text='LATER')
        earlier=dict(later,id='earlier',text='EARLIER')
        now=time.time()
        self.adapter.inbox.put(later,received_at=now)
        self.adapter.inbox.put(earlier,received_at=now-.1)
        self.assertEqual([item['id'] for item in self.adapter.inbox.take_batch(1,now=now+2)],['earlier','later'])

    async def test_unresolved_lid_holds_dispatch_not_ws_reader(self):
        payload=event();payload['data']['message']['sender']['jid']='100123@lid'
        payload['data']['message']['chat']['jid']='100123@lid'
        self.adapter.ws_ingress=LaneQueue(self.adapter.ingest_queued,lambda item:self.adapter.ingress_key(item[0]))
        self.adapter.ws_ingress.put((payload,'websocket',time.time()),100)
        self.assertEqual(self.adapter.admission_principals(),{OWNER})
        await self.adapter.ws_ingress.close()

    async def test_delayed_identity_before_stop_cannot_resurrect_work(self):
        now=time.time();stop=norm(event());stop.update(id='stop',text='/stop')
        self.adapter.inbox.put(stop,received_at=now)
        self.adapter.inbox.take_batch(0,stops_only=True)
        earlier=dict(stop,id='delayed',text='old work')
        self.assertEqual(self.adapter.inbox.put(earlier,received_at=now-.1),'cancelled')
        self.assertEqual(self.adapter.inbox.take_batch(0),[])

    async def test_shared_queue_reserves_bounded_small_stop_slots(self):
        q=LaneQueue(AsyncMock(),lambda item:'fixture',max_items=1,max_bytes=10)
        self.assertTrue(q.put('normal',10));self.assertFalse(q.put('extra',1))
        for _ in range(10):self.assertTrue(q.put('stop',10,control=True))
        self.assertFalse(q.put('stop',10,control=True))
        await q.close()

class QueueAndProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_worker_marks_truncation(self):
        from ryzeapi.stt_worker import transcribe
        with patch('tools.transcription_tools.transcribe_audio',return_value={'success':True,'transcript':'x'*16001}):
            text=transcribe('/synthetic')
        self.assertTrue(text.startswith('x'*16000));self.assertIn('truncada',text)

    async def test_slow_lane_does_not_block_reader_or_other_contact(self):
        release=asyncio.Event();fast=asyncio.Event();seen=[]
        async def handler(item):
            if item[0]=='slow':await release.wait()
            seen.append(item)
            if item[0]=='fast':fast.set()
        q=LaneQueue(handler,lambda item:item[0],max_items=3,max_bytes=30)
        q.start()
        try:
            self.assertTrue(q.put(('slow',1),10));self.assertTrue(q.put(('slow',2),10));self.assertTrue(q.put(('fast',1),10))
            self.assertFalse(q.put(('other',1),1))
            await asyncio.wait_for(fast.wait(),1);self.assertEqual(seen,[('fast',1)])
            release.set()
            for _ in range(10):
                if q.count==0:break
                await asyncio.sleep(.01)
            self.assertEqual(seen,[('fast',1),('slow',1),('slow',2)]);self.assertEqual(q.bytes,0)
        finally:release.set();await q.close()

    async def test_stt_cancel_reaps_process_and_next_job_can_run(self):
        created=asyncio.Event();processes=[];original=asyncio.create_subprocess_exec
        async def spawn(*args,**kwargs):
            proc=await original(*args,**kwargs);processes.append(proc);created.set();return proc
        with patch('ryzeapi.stt.command',return_value=[sys.executable,'-c','import time;time.sleep(60)']),patch('ryzeapi.stt.asyncio.create_subprocess_exec',side_effect=spawn):
            task=asyncio.create_task(run_stt('/synthetic'))
            await asyncio.wait_for(created.wait(),2);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNotNone(processes[0].returncode)
        with self.assertRaises(ProcessLookupError):os.kill(processes[0].pid,0)
        with patch('ryzeapi.stt.command',return_value=[sys.executable,'-c','print("{\\\"transcript\\\":\\\"next job\\\"}")']):
            self.assertEqual(await run_stt('/synthetic'),'next job')

    async def test_stt_excessive_output_is_bounded_and_reaped(self):
        with patch('ryzeapi.stt.command',return_value=[sys.executable,'-c','import sys,time;sys.stdout.write("x"*200000);sys.stdout.flush();time.sleep(60)']):
            with self.assertRaises(ValueError):await asyncio.wait_for(run_stt('/synthetic'),3)

    async def test_stt_ignoring_term_is_killed(self):
        ready=asyncio.Event();processes=[];original=asyncio.create_subprocess_exec
        async def spawn(*args,**kwargs):
            proc=await original(*args,**kwargs);processes.append(proc)
            # Worker announces that SIGTERM is now ignored; consume only this fixture marker.
            self.assertEqual(await proc.stdout.readline(),b'READY\n');ready.set();return proc
        code='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("READY",flush=True);time.sleep(60)'
        with patch('ryzeapi.stt.command',return_value=[sys.executable,'-c',code]),patch('ryzeapi.stt.asyncio.create_subprocess_exec',side_effect=spawn):
            task=asyncio.create_task(run_stt('/synthetic'));await asyncio.wait_for(ready.wait(),2);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,4)
        self.assertEqual(processes[0].returncode,-signal.SIGKILL)

    async def test_status_client_only_gets_fixed_endpoint(self):
        calls=[]
        def handle(request):calls.append(request);return httpx.Response(200,json={'success':True,'message_id':'id','status':'read'})
        client=RyzeClient('fixture','synthetic',transport=httpx.MockTransport(handle))
        try:await client.message_status('id')
        finally:await client.close()
        self.assertEqual(calls[0].method,'GET');self.assertEqual(calls[0].url.path,'/api/chat/status/fixture')

    async def test_timings_bounded_whitelist(self):
        t=Timings()
        for i in range(1000):t.observe('send_text',i/1000)
        for key,value in [('secret',1),('send_text',float('nan')),('send_text',-1)]:t.observe(key,value)
        result=t.summary();self.assertEqual(set(result),{'send_text'})
        self.assertEqual(result['send_text']['count'],1000);self.assertEqual(result['send_text']['window_samples'],256)
