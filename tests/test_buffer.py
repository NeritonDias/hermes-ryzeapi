import asyncio, base64, json, sqlite3, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import test_ryzeapi as original
from test_ryzeapi import event, norm, OWNER
from ryzeapi.core import Inbox

class BufferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'inbox.db'
        self.inbox=Inbox(self.path)
    def tearDown(self): self.inbox.close();self.temp.cleanup()
    def put(self, mid, received, text='hello', number=OWNER):
        item=norm(event());item.update(id=mid,text=text,number=number)
        with patch('ryzeapi.core.time.time',return_value=received): self.inbox.put(item)

    def test_quiet_period_resets_and_groups_ordered(self):
        self.put('a',100);self.put('b',108)
        self.assertEqual(self.inbox.take_batch(10,now=110),[])
        batch=self.inbox.take_batch(10,now=118)
        self.assertEqual([i['id'] for i in batch],['a','b'])
        self.inbox.finish_batch(batch,True)
        self.assertEqual(self.inbox.db.execute('select distinct status,payload from inbox').fetchall(),[('admitted','{}')])

    def test_duplicate_does_not_extend_wait(self):
        self.put('a',100);self.put('a',109)
        self.assertEqual(len(self.inbox.take_batch(10,now=110)),1)

    def test_never_mix_contacts_or_block_ready_contact(self):
        self.put('a',100,number=OWNER);self.put('b',109,number=OWNER)
        self.put('friend',101,number='5511888888888')
        batch=self.inbox.take_batch(10,now=111)
        self.assertEqual([i['id'] for i in batch],['friend'])

    def test_zero_immediate_and_control_command_bypass(self):
        self.put('a',100);self.put('b',100)
        self.assertEqual(len(self.inbox.take_batch(0,now=100)),1)
        self.put('stop',101,text='/stop')
        self.assertEqual([i['id'] for i in self.inbox.take_batch(60,now=101)],['stop'])

    def test_hard_deadline_and_count_bound(self):
        self.put('first',100);self.put('last',219)
        self.assertEqual(len(self.inbox.take_batch(60,now=220)),2)
        for i in range(20): self.put('cap'+str(i),300)
        self.assertEqual(len(self.inbox.take_batch(60,now=300)),20)

    def test_stop_cancels_only_earlier_buffer_for_same_contact(self):
        self.put('before',100);self.put('other',100,number='5511888888888')
        self.put('stop',101,text='/stop');self.put('after',102)
        self.assertEqual([i['id'] for i in self.inbox.take_batch(60,now=102)],['stop'])
        self.assertEqual(self.inbox.db.execute("select status,payload from inbox where id='before'").fetchone(),('cancelled','{}'))
        self.assertEqual(self.inbox.db.execute("select count(*) from inbox where status='pending'").fetchone()[0],2)

    def test_restart_preserves_buffer_and_uncertain_whole_batch(self):
        self.put('a',100);self.put('b',101)
        self.inbox.close();self.inbox=Inbox(self.path)
        self.assertEqual(self.inbox.take_batch(10,now=109),[])
        self.assertEqual(len(self.inbox.take_batch(10,now=111)),2)
        self.inbox.close();self.inbox=Inbox(self.path)
        self.assertEqual(self.inbox.db.execute('select distinct status,payload from inbox').fetchall(),[('uncertain','{}')])

    def test_old_schema_migrates_pending_without_losing_payload(self):
        self.inbox.close()
        legacy=Path(self.temp.name)/'legacy.db'
        with sqlite3.connect(legacy) as db:
            db.execute('CREATE TABLE inbox(id TEXT PRIMARY KEY,payload TEXT,status TEXT,created REAL)')
            item=norm(event())
            db.execute('INSERT INTO inbox VALUES (?,?,?,?)',(item['id'],json.dumps(item),'pending',100))
        self.inbox=Inbox(legacy)
        batch=self.inbox.take_batch(10,now=111)
        self.assertEqual(batch[0]['text'],'Olá Hermes')

class BatchedAdapterTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=original.AdapterTests.asyncSetUp
    asyncTearDown=original.AdapterTests.asyncTearDown
    async def test_text_voice_image_single_native_handoff(self):
        from gateway.run import _event_media_is_stt_input, _event_media_is_image
        received=[]
        async def handle(e): received.append(e);e._gateway_accepted=True;self.adapter._running=False
        self.adapter.handle_message=handle
        for i,media in enumerate((None,{'kind':'ptt','mime':'audio/mpeg','base64':base64.b64encode(b'ID3fixture').decode()},
                                  {'kind':'image','mime':'image/png','base64':base64.b64encode(b'PNGfixture').decode()})):
            item=norm(event());item.update(id=str(i),text='Analyze together' if i==0 else '',media=media)
            self.adapter.inbox.put(item)
        self.adapter.inbox.db.execute('update inbox set created=?',(time.time()-11,));self.adapter.inbox.db.commit()
        value={'enabled':True,'instance':'hermes-test','webhook_secret':'s'*40,'allowed_users':OWNER,'buffer_seconds':10}
        self.adapter._running=True
        with patch('ryzeapi.adapter.load',return_value=value),patch('ryzeapi.adapter.get_hermes_home',return_value=Path(self.temp.name)):
            await asyncio.wait_for(self.adapter.consume(),timeout=2)
        self.assertEqual(len(received),1)
        e=received[0]
        self.assertEqual(len(e.media_urls),1);self.assertEqual(e.message_id,'2')
        self.assertIn('Analyze together',e.text)
        self.assertIn('Transcrição sintética',e.text)
        self.assertTrue(_event_media_is_image(e,0))
        self.assertFalse(_event_media_is_stt_input(e,0))
        self.assertEqual(self.adapter.stats['last_batch_size'],3)
        self.assertEqual(self.adapter.inbox.db.execute("select count(*) from inbox where status='admitted'").fetchone()[0],3)
