"""Synthetic response envelopes; no network, credentials or real conversations."""
import copy, json, unittest, sqlite3
from contextlib import closing
import test_groups
from test_groups import group_event, GID, OTHER
from test_ryzeapi import OWNER
from ryzeapi.core import canonical_envelope
from ryzeapi.interactions import InteractionStore,correlate


class InteractiveReplyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_groups.GroupAdapterTests.asyncSetUp
    asyncTearDown=test_groups.GroupAdapterTests.asyncTearDown
    def response(self, kind='buttons', mid='click', reference='sent-menu'):
        value=group_event(mid)
        data=value['data'];msg=data['message']
        for field in ('id','direction','timestamp','chat','sender'):
            data[field]=msg.pop(field)
        msg['content']=''
        msg['type']='buttons_response' if kind=='buttons' else 'list_response'
        data['reply']={'message_id':reference}
        data['interactive']={'selectedButtonId':'confirmar'} if kind=='buttons' else {'selectedRowId':'lista_ok'}
        return value

    async def test_outer_metadata_reaches_model_once(self):
        self.store.configure(GID,'respond','mentions','all')
        self.adapter.telemetry.sent('sent-menu',GID)
        for kind,choice in (('buttons','confirmar'),('list','lista_ok')):
            value=self.response(kind,mid=kind)
            before=copy.deepcopy(value)
            normalized=canonical_envelope(value)
            self.assertEqual(value,before)
            self.assertEqual(canonical_envelope(normalized),normalized)
            self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
            self.assertEqual(await self.adapter.ingest(value,'webhook'),'duplicate')
            record,_=self.store.record(value)
            self.assertIn(choice,record['text'])
            self.assertEqual(record['reply_id'],'sent-menu')
            item=self.adapter.inbox.take()
            self.assertIn(choice,item['text'])
            self.assertEqual(item['reply_id'],'sent-menu')
            event,_=await self.adapter.prepare_batch([item])
            self.assertIn(choice,event.text)
            self.assertTrue(event.source.role_authorized)
            self.assertNotIn('DO-NOT-STORE',json.dumps(item))

    async def test_unknown_and_other_group_references_do_not_trigger(self):
        self.store.configure(GID,'respond','mentions','all')
        self.adapter.telemetry.sent('sent-menu',OTHER)
        for kind in ('buttons','list'):
            self.assertEqual(await self.adapter.ingest(self.response(kind,kind),'websocket'),'observed')
        self.assertIsNone(self.adapter.inbox.take())

    async def test_listen_and_sender_allowlist_still_apply(self):
        self.adapter.telemetry.sent('sent-menu',GID)
        self.store.configure(GID,'listen','mentions','all')
        self.assertEqual(await self.adapter.ingest(self.response(),'websocket'),'observed')
        self.store.configure(GID,'respond','mentions','authorized')
        value=self.response(mid='outsider');value['data']['sender']['jid']='5511777777777'
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'ignored')
        self.assertIsNone(self.adapter.inbox.take())

    async def test_outer_reference_cannot_be_overridden_by_nested_reference(self):
        self.store.configure(GID,'respond','mentions','all')
        self.adapter.telemetry.sent('sent-menu',GID)
        value=self.response(reference='foreign-message')
        value['data']['message']['reply']={'message_id':'sent-menu'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'observed')

    def wire_response(self,kind,wire,mid='wire-click'):
        value=self.response(kind,mid)
        del value['data']['reply'];del value['data']['interactive']
        value['data']['message']['context']=None
        value['data']['message']['interactive']=({'selectedButtonId':wire} if kind=='buttons' else
            {'selectedReply':{'selectedRowID':wire},'title':'Funcionou'})
        return value

    def sent_choice(self,kind='buttons',chat=GID,accepted=True):
        store=InteractionStore(self.store.root,'hermes-test')
        payload=({'contentText':'Menu de teste','buttons':[{'id':'logical-choice','displayText':'Confirmar'}]} if kind=='buttons' else
            {'contentText':'Menu de teste','sections':[{'title':'Opções','rows':[{'id':'logical-choice','title':'Funcionou'}]}]})
        wire,choices=store.prepare(kind,payload,chat)
        if accepted:store.accepted(choices,'sent-menu');self.adapter.telemetry.sent('sent-menu',chat)
        store.close()
        return choices[0]

    async def test_observed_button_and_list_without_quote_reach_native_event_once(self):
        self.store.configure(GID,'respond','mentions','all')
        for kind in ('buttons','list'):
            wire=self.sent_choice(kind)
            value=self.wire_response(kind,wire,kind)
            self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
            self.assertEqual(await self.adapter.ingest(value,'webhook'),'duplicate')
            item=self.adapter.inbox.take()
            self.assertIn('logical-choice',item['text']);self.assertNotIn(wire,item['text'])
            self.assertEqual(item['reply_id'],'sent-menu')
            event,_=await self.adapter.prepare_batch([item])
            self.assertIn('logical-choice',event.text)
            self.assertEqual(event.reply_to_text,'Menu de teste')
            archived=json.loads(self.store.db.execute('SELECT record FROM group_archive WHERE key=?',('message:'+kind,)).fetchone()[0])
            self.assertIn('logical-choice',archived['text'])

    async def test_unconfirmed_foreign_unknown_and_expired_capabilities_rejected(self):
        self.store.configure(GID,'respond','mentions','all')
        unknown='hry_'+'0'*32
        pending=self.sent_choice(accepted=False)
        foreign=self.sent_choice(chat=OTHER)
        expired=self.sent_choice()
        with closing(sqlite3.connect(self.store.root/'interactions.db')) as db:
            with db:db.execute('UPDATE choices SET created=0 WHERE wire=?',(expired,))
        for index,wire in enumerate((unknown,pending,foreign,expired)):
            self.assertEqual(await self.adapter.ingest(self.wire_response('buttons',wire,str(index)),'websocket'),'observed')
        self.assertIsNone(self.adapter.inbox.take())

    async def test_correlation_does_not_bypass_sender_mode_or_instance(self):
        wire=self.sent_choice()
        value=self.wire_response('buttons',wire)
        self.store.configure(GID,'respond','mentions','authorized')
        value['data']['sender']['jid']='5511777777777'
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'ignored')
        self.store.configure(GID,'listen','mentions','all')
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'observed')
        msg=canonical_envelope(value)['data']['message']
        self.assertFalse(correlate(self.store.root,'other-instance',GID,msg)[1])
        msg['reply']={'message_id':'foreign-menu'}
        self.assertFalse(correlate(self.store.root,'hermes-test',GID,msg)[1])
        del msg['reply']
        msg['type']='text'
        self.assertFalse(correlate(self.store.root,'hermes-test',GID,msg)[1])

    async def test_copy_url_call_untouched_and_repeated_logical_ids_have_distinct_wire_ids(self):
        store=InteractionStore(self.store.root,'hermes-test')
        payload={'buttons':[{'id':'CODE','displayText':'Copy','type':'COPY'},
                            {'id':'https://example.com','displayText':'URL','type':'URL'},
                            {'id':'+5511999999999','displayText':'Call','type':'CALL'}]}
        wire,choices=store.prepare('buttons',payload,GID)
        self.assertEqual(wire,payload);self.assertEqual(choices,[])
        store.close()
        self.assertNotEqual(self.sent_choice(),self.sent_choice())
