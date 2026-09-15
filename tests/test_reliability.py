"""Reliability regressions: synthetic data, no Ryze account or WhatsApp sends."""
import asyncio, base64, json, os, sqlite3, time, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import test_ryzeapi as original
from test_ryzeapi import norm, event, OWNER
from ryzeapi.core import Inbox
from ryzeapi.maintenance import clean_media_cache
from ryzeapi.client import RyzeClient, RyzeError
import httpx

class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = original.AdapterTests.asyncSetUp
    asyncTearDown = original.AdapterTests.asyncTearDown

    def put(self, mid, text='hello', audio=False, number=OWNER):
        item = norm(event()); item.update(id=mid, text=text, number=number)
        if audio: item['media'] = {'kind':'ptt','mime':'audio/ogg','base64':base64.b64encode(b'OggSfixture').decode()}
        self.adapter.inbox.put(item)
        return item

    async def start(self):
        self.adapter._running = True
        self.adapter.last_housekeeping = time.monotonic()
        self.adapter.worker = asyncio.create_task(self.adapter.consume())

    async def stop(self):
        self.adapter._running = False
        await asyncio.wait_for(self.adapter.worker, 3)

    async def health(self):
        class Request: headers = {'Authorization':'Bearer '+'s'*40}
        return json.loads((await self.adapter.health(Request())).body)

    async def test_stop_preempts_stt_and_never_admits_cancelled_audio(self):
        entered = asyncio.Event(); never = asyncio.Event(); stopped = asyncio.Event(); received = []
        async def transcribe(path): entered.set(); await never.wait()
        async def handle(e):
            received.append(e.text); e._gateway_accepted = True
            if e.text == '/stop': stopped.set()
        self.adapter.transcribe_voice.side_effect = transcribe
        self.adapter.handle_message = handle
        self.adapter.send_transcripts = AsyncMock()
        self.put('audio', audio=True)
        with patch('ryzeapi.adapter.get_hermes_home', return_value=Path(self.temp.name)):
            await self.start()
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.put('stop', '/stop')
                await asyncio.wait_for(stopped.wait(), 2)
                self.assertEqual(received, ['/stop'])
                self.assertEqual(self.adapter.inbox.db.execute("SELECT status,payload FROM inbox WHERE id='audio'").fetchone(), ('cancelled','{}'))
            finally: await self.stop()

    async def test_transcription_does_not_block_other_contact(self):
        other = '5511888888888'; entered = asyncio.Event(); received = asyncio.Event()
        async def transcribe(path): entered.set(); await asyncio.Event().wait()
        async def handle(e): e._gateway_accepted = True; received.set()
        self.adapter.transcribe_voice.side_effect = transcribe; self.adapter.handle_message = handle
        self.adapter.allowed.add(other)
        self.put('audio', audio=True); self.put('other', number=other)
        with patch.object(self.adapter, 'current', return_value=True), patch('ryzeapi.adapter.get_hermes_home', return_value=Path(self.temp.name)):
            await self.start()
            try:
                await asyncio.wait_for(entered.wait(), 2)
                await asyncio.wait_for(received.wait(), 2)
            finally: await self.stop()

    async def test_transient_sql_failure_recovers_and_health_is_truthful(self):
        original_take = self.adapter.inbox.take_batch
        calls = 0
        def take(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1: raise sqlite3.OperationalError('synthetic lock')
            return original_take(*args, **kwargs)
        with patch.object(self.adapter.inbox, 'take_batch', side_effect=take):
            await self.start()
            try:
                await asyncio.sleep(.05)
                self.assertFalse((await self.health())['running'])
                await asyncio.sleep(.65)
                self.assertTrue((await self.health())['consumer_healthy'])
                self.assertEqual(self.adapter.stats['consumer_errors'], 1)
            finally: await self.stop()
        self.assertFalse((await self.health())['running'])

    async def test_finalization_failure_is_retried_without_second_handoff(self):
        original_set = self.adapter.inbox.set_batch_status; failed = False
        def set_status(batch, status, **kwargs):
            nonlocal failed
            if status == 'admitted' and not failed:
                failed = True; raise sqlite3.OperationalError('synthetic finalization lock')
            return original_set(batch, status, **kwargs)
        async def handle(e): e._gateway_accepted = True
        self.adapter.handle_message = AsyncMock(side_effect=handle)
        self.put('once')
        with patch.object(self.adapter.inbox, 'set_batch_status', side_effect=set_status):
            await self.start()
            try: await asyncio.sleep(.8)
            finally: await self.stop()
        self.assertEqual(self.adapter.handle_message.await_count, 1)
        self.assertEqual(self.adapter.inbox.db.execute("SELECT status FROM inbox WHERE id='once'").fetchone()[0], 'admitted')

    async def test_old_pending_expired_after_restart(self):
        self.put('old')
        self.adapter.inbox.db.execute('UPDATE inbox SET created=?', (time.time()-20*86400,)); self.adapter.inbox.db.commit()
        path = Path(self.temp.name)/'inbox.db'
        self.adapter.inbox.close(); self.adapter.inbox = Inbox(path)
        self.assertEqual(self.adapter.inbox.take_batch(0), [])
        self.assertEqual(self.adapter.inbox.db.execute('SELECT status,payload FROM inbox').fetchone(), ('expired','{}'))

    async def test_preparation_can_resume_but_handoff_cannot(self):
        self.put('safe'); self.put('uncertain', number='5511888888888')
        self.adapter.inbox.take_batch(0, claim='preparing')
        self.adapter.inbox.take_batch(0)
        self.adapter.inbox.close(); self.adapter.inbox = Inbox(Path(self.temp.name)/'inbox.db')
        self.assertEqual(self.adapter.inbox.db.execute('SELECT id,status FROM inbox ORDER BY id').fetchall(), [('safe','pending'),('uncertain','uncertain')])

    async def test_cache_only_removes_old_owned_regular_files(self):
        directory = Path(self.temp.name)/'cache'; directory.mkdir()
        old = directory/('a'*64+'.ogg'); old.write_bytes(b'old'); os.utime(old, (100,100))
        fresh = directory/('b'*64+'.png'); fresh.write_bytes(b'fresh')
        unrelated = directory/'notes.txt'; unrelated.write_text('keep'); os.utime(unrelated, (100,100))
        link = directory/('c'*64+'.txt'); link.symlink_to(unrelated)
        self.assertEqual(clean_media_cache(directory), 1)
        self.assertFalse(old.exists()); self.assertTrue(fresh.exists()); self.assertTrue(unrelated.exists()); self.assertTrue(link.is_symlink())

    async def test_stt_timeout_waits_cleanup_before_next_worker(self):
        from ryzeapi.adapter import RyzeAdapter
        cleaned = []
        async def backend(*args):
            try: await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.01)
                cleaned.append(True)
        self.adapter.stt_timeout = .03
        with patch('ryzeapi.adapter.run_stt', side_effect=backend) as mock:
            self.assertIsNone(await RyzeAdapter.transcribe_voice(self.adapter, Path('/fixture')))
            self.assertTrue(self.adapter.stt_task.done());self.assertEqual(len(cleaned),1)
            self.assertIsNone(await RyzeAdapter.transcribe_voice(self.adapter, Path('/second')))
            self.assertEqual(mock.call_count,2);self.assertEqual(len(cleaned),2)

    async def test_expiry_uses_original_timestamp_not_only_queue_age(self):
        from datetime import datetime, timezone
        item = norm(event()); item['id']='source-old'
        item['timestamp'] = datetime.fromtimestamp(time.time()-86401, timezone.utc).isoformat()
        self.adapter.inbox.put(item)
        self.assertEqual(self.adapter.inbox.take_batch(0), [])

    async def test_stop_does_not_cancel_a_different_contacts_preparation(self):
        other = '5511888888888'
        self.put('other', number=other)
        self.put('stop', '/stop')
        self.adapter.inbox.take_batch(0, stops_only=True, claim='preparing')
        self.assertEqual(self.adapter.inbox.db.execute("SELECT status FROM inbox WHERE id='other'").fetchone()[0], 'pending')

    async def test_same_contact_remains_ordered_while_preparing(self):
        self.put('first')
        self.adapter.inbox.take_batch(0, claim='preparing')
        self.put('second')
        self.assertEqual(self.adapter.inbox.take_batch(0, exclude={OWNER}), [])

    async def test_transcript_budget_and_original_document_name(self):
        self.adapter.transcribe_voice.return_value = 'x'*20000
        items = [self.put(str(i), audio=True) for i in range(3)]
        with patch('ryzeapi.adapter.get_hermes_home', return_value=Path(self.temp.name)):
            e, transcripts = await self.adapter.prepare_batch(items)
        self.assertLess(len(e.text), 35000)
        self.assertEqual(len(transcripts), 2)
        self.assertIn('truncada', e.text)
        document = self.put('document')
        document['media'] = {'kind':'document','mime':'text/plain','filename':'relatorio.txt','base64':'YQ=='}
        with patch('ryzeapi.adapter.get_hermes_home', return_value=Path(self.temp.name)):
            e, _ = await self.adapter.prepare_batch([document])
        self.assertIn('relatorio.txt', e.text)

    async def test_full_queue_reserves_bounded_stop_slots(self):
        for i in range(100): self.put(str(i))
        item = norm(event()); item.update(id='overflow')
        self.assertEqual(self.adapter.inbox.put(item), 'full')
        item['text'] = '/stop'
        for i in range(10):
            item['id'] = 'stop'+str(i)
            self.assertEqual(self.adapter.inbox.put(item), 'queued')
        item['id'] = 'stop-overflow'
        self.assertEqual(self.adapter.inbox.put(item), 'full')

class SafeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_safe_get_but_never_post(self):
        calls = []
        def handle(req):
            calls.append(req.method)
            return httpx.Response(503 if len(calls) == 1 else 200, json={'success':True})
        client = RyzeClient('hermes-test', 'fixture', transport=httpx.MockTransport(handle))
        try:
            await client.envelope('GET', '/fixture')
            self.assertEqual(calls, ['GET','GET'])
            calls.clear()
            with self.assertRaises(RyzeError): await client.envelope('POST', '/fixture')
            self.assertEqual(calls, ['POST'])
        finally: await client.close()

    async def test_rate_reset_prevents_flood_and_redacts_body(self):
        calls = []
        def handle(req):
            calls.append(req)
            return httpx.Response(429, headers={'X-RateLimit-Reset':str(time.time()+60)}, text='SECRET')
        client = RyzeClient('hermes-test', 'fixture', transport=httpx.MockTransport(handle))
        try:
            for method in ('GET','POST'):
                with self.assertRaises(RyzeError) as caught: await client.envelope(method, '/fixture')
                self.assertEqual(caught.exception.status, 429)
                self.assertNotIn('SECRET', str(caught.exception))
            self.assertEqual(len(calls), 1)
        finally: await client.close()

    async def test_audio_attachment_and_voice_note_are_distinct(self):
        values = []
        def handle(req):
            values.append(json.loads(req.content)['isVoice'])
            return httpx.Response(200, json={'success':True,'data':{'messageId':'fixture'}})
        client = RyzeClient('hermes-test', 'fixture', transport=httpx.MockTransport(handle))
        try:
            for voice in (False,True): await client.send_media(OWNER,'YQ==','audio','audio/mpeg','a.mp3',is_voice=voice)
            self.assertEqual(values, [False,True])
        finally: await client.close()

    async def test_websocket_changes_only_when_needed_and_reads_back(self):
        calls = []
        desired = {'enabled':True,'events':['message.exchange','instance.state','message.status','group.flow'],'mediaBase64':True}
        def handle(req):
            calls.append(req.method)
            return httpx.Response(200,json={'success':True,'websocket':{} if len(calls)==1 else desired})
        client = RyzeClient('hermes-test','fixture',transport=httpx.MockTransport(handle))
        try:
            await client.ensure_websocket()
            self.assertEqual(calls, ['GET','POST','GET'])
        finally: await client.close()
