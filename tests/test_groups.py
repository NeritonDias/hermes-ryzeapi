"""Group policy/archive regressions, synthetic data only."""
import asyncio, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
import test_ryzeapi as original
from test_ryzeapi import event, OWNER
from ryzeapi.groups import GroupStore, group_id
from ryzeapi.telemetry import Telemetry

GID='120363000000000001@g.us'
OTHER='120363000000000002@g.us'

def group_event(mid='group-message', sender=OWNER):
    value=event();msg=value['data']['message']
    msg['id']=mid;msg['chat']={'jid':GID,'name':'Grupo sintético','type':'group'}
    msg['sender']={'jid':sender,'name':'Membro sintético'}
    return value

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=GroupStore(self.root,'hermes-test')
        self.store.sync([{'groupJid':GID,'name':'Grupo sintético','memberCount':2}])
    def tearDown(self): self.store.close();self.temp.cleanup()
    def test_catalog_does_not_make_folders_or_grant_access(self):
        self.assertEqual(self.store.policy(GID)['mode'],'blocked')
        self.assertEqual(self.store.record(group_event()),(None,False))
        self.assertFalse((self.root/'group-conversations').exists())
    def test_sync_preserves_policy_adds_blocked_and_marks_missing(self):
        self.store.configure(GID,'listen','mentions')
        self.store.sync([{'groupJid':GID,'name':'Novo nome'},{'groupJid':OTHER,'name':'Outro'}])
        self.assertEqual(self.store.policy(GID)['mode'],'listen')
        self.assertEqual(self.store.policy(OTHER)['mode'],'blocked')
        with self.assertRaises(ValueError): self.store.sync([{'groupJid':'../../oops'}])
        self.assertTrue(self.store.policy(GID)['present'])
        self.store.sync([]);self.assertFalse(self.store.policy(GID)['present'])
    def test_instance_isolation(self):
        self.store.configure(GID,'respond','all','all')
        with GroupStore(self.root,'another') as other:
            self.assertEqual(other.list(),[]);self.assertEqual(other.policy(GID)['mode'],'blocked')
    def test_archive_dedup_no_secrets_and_lazy_dates(self):
        self.store.configure(GID,'listen','mentions')
        value=group_event();value['instanceData']['token']='SECRET-NEVER-ARCHIVE'
        record,fresh=self.store.record(value);self.assertTrue(fresh)
        self.assertEqual(record['member']['number'],OWNER)
        self.assertFalse(self.store.record(value)[1])
        files=list((self.root/'group-conversations').rglob('*.json'));self.assertEqual(len(files),1)
        self.assertNotIn('SECRET',files[0].read_text());self.assertEqual(files[0].stat().st_mode&0o777,0o600)
        files[0].unlink();self.store.record(value);self.assertTrue(files[0].exists())
    def test_membership_events_no_fake_phone_for_lid(self):
        self.store.configure(GID,'listen','mentions')
        for kind in ('joined','left'):
            value=group_event();value['event']='group.flow';value['data']={
                'type':kind,'groupJid':GID,'groupName':'Grupo sintético','timestamp':event()['data']['message']['timestamp'],
                'participants':[{'jid':'123456789@lid','name':'Pessoa'}]}
            record,fresh=self.store.record(value)
            self.assertTrue(fresh);self.assertEqual(record['members'][0]['number'],'')
        self.assertEqual(len(list((self.root/'group-conversations').rglob('*.json'))),2)
    def test_identity_validation(self):
        for value in ('*','../../name','status@broadcast','5511999999999','123@newsletter'):
            self.assertFalse(group_id(value))

class GroupAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await original.AdapterTests.asyncSetUp(self)
        self.adapter.group_store=GroupStore(Path(self.temp.name)/'ryzeapi','hermes-test')
        self.store=self.adapter.group_store
        self.store.sync([{'groupJid':GID,'name':'Grupo sintético'}])
        self.adapter.telemetry=Telemetry(self.adapter.inbox.db)
        self.adapter.client=AsyncMock();self.adapter.client.send_text.return_value='sent-group'
        self.adapter.bot_number='5511888888888'
    async def asyncTearDown(self):
        self.store.close();await original.AdapterTests.asyncTearDown(self)
    async def test_listen_archives_without_model_or_send(self):
        self.store.configure(GID,'listen','all','all')
        self.adapter.handle_message=AsyncMock()
        self.assertEqual(await self.adapter.ingest(group_event(),'websocket'),'observed')
        self.assertIsNone(self.adapter.inbox.take());self.adapter.handle_message.assert_not_awaited()
        self.assertFalse((await self.adapter.send(GID,'No')).success)
        self.adapter.client.send_text.assert_not_awaited()
    async def test_restricted_senders_and_all_members_are_group_scoped(self):
        outsider='5511777777777'
        self.store.configure(GID,'respond','all','authorized')
        self.assertEqual(await self.adapter.ingest(group_event('one',outsider),'websocket'),'ignored')
        self.store.configure(GID,'respond','all','all')
        self.assertEqual(await self.adapter.ingest(group_event('two',outsider),'websocket'),'queued')
        item=self.adapter.inbox.take();self.assertEqual(item['number'],GID)
        e,_=await self.adapter.prepare_batch([item])
        self.assertEqual(e.source.chat_type,'group');self.assertEqual(e.source.user_id,outsider)
        self.assertIs(e.source.role_authorized,True)
        value=event();value['data']['message']['sender']['jid']=outsider
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'ignored')
        self.assertFalse((await self.adapter.send(outsider,'No')).success)
    async def test_mention_reply_trigger_and_transport_dedup(self):
        self.store.configure(GID,'respond','mentions')
        self.assertEqual(await self.adapter.ingest(group_event(),'websocket'),'observed')
        value=group_event('ping');value['data']['message']['content']={'text':'@5511888888888 olá'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'duplicate')
        self.adapter.telemetry.sent('known-reply',GID)
        value=group_event('reply');value['data']['message']['reply']={'message_id':'known-reply'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
    async def test_revocation_cancels_queue_and_blocks_outbound(self):
        self.store.configure(GID,'respond','all')
        await self.adapter.ingest(group_event(),'websocket');item=self.adapter.inbox.take()
        self.assertTrue(self.adapter.item_authorized(item))
        self.store.configure(GID,'listen','all')
        self.assertFalse(self.adapter.item_authorized(item))
        self.assertFalse((await self.adapter.send(GID,'No')).success)
    async def test_group_destination_is_not_stripped_into_a_phone(self):
        self.store.configure(GID,'respond','all')
        self.assertTrue((await self.adapter.send(GID,'Sim')).success)
        self.adapter.client.send_text.assert_awaited_once_with(GID,'Sim',None)
        self.assertFalse((await self.adapter.send(OTHER,'No')).success)

    async def test_verified_lid_text_queues_once_across_both_transports(self):
        self.store.configure(GID,'respond','mentions','all')
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        value=group_event('lid-ping');value['data']['message']['content']={'text':'@12345678901234 oi'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'duplicate')
        self.adapter.client.own_lid_for.assert_awaited_once_with('5511888888888')
        item=self.adapter.inbox.take()
        self.assertEqual(item['number'],GID)
        e,_=await self.adapter.prepare_batch([item])
        self.assertEqual(e.source.chat_type,'group')
        self.assertTrue(e.source.role_authorized)

    async def test_lid_metadata_in_live_outer_envelope(self):
        self.store.configure(GID,'respond','mentions')
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        value=group_event('outer-lid');msg=value['data']['message']
        value['data']={**msg,'message':{'content':'Olá Hermes'},'mentions':{'mentionedUsers':['12345678901234@lid']}}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'queued')

    async def test_identity_cold_start_and_parallel_cache(self):
        self.adapter.set_bot_number('')
        self.adapter.client.connection_state.return_value='connected'
        self.adapter.client.own_number='5511888888888'
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        self.assertTrue(all(await asyncio.gather(*(self.adapter.refresh_bot_identity() for _ in range(5)))))
        self.adapter.client.connection_state.assert_awaited_once()
        self.adapter.client.own_lid_for.assert_awaited_once()

    async def test_unrelated_lid_and_prefix_do_not_activate(self):
        self.store.configure(GID,'respond','mentions')
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        await self.adapter.refresh_bot_identity()
        for i,text in enumerate(('@98765432101234 oi','@123456789012345 oi','@12345678901234abc','email@12345678901234','@Hermes oi')):
            value=group_event('wrong-'+str(i));value['data']['message']['content']={'text':text}
            self.assertEqual(await self.adapter.ingest(value,'websocket'),'observed')
        self.assertIsNone(self.adapter.inbox.take())

    async def test_lid_is_group_scoped_and_does_not_bypass_sender_policy(self):
        self.store.configure(GID,'respond','mentions','authorized')
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        value=group_event('outsider-lid','5511777777777');value['data']['message']['content']={'text':'@12345678901234 oi'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'ignored')
        self.store.configure(GID,'listen','mentions','all')
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'observed')
        self.store.configure(GID,'blocked','mentions','all')
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'ignored')
        value=event();value['data']['message']['sender']['jid']='5511777777777'
        value['data']['message']['content']={'text':'@12345678901234 oi'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'ignored')

    async def test_missing_identity_defers_with_backoff_then_recovers(self):
        from ryzeapi.client import RyzeError
        self.store.configure(GID,'respond','mentions')
        self.adapter.client.own_lid_for.side_effect=RyzeError('Synthetic unavailable')
        value=group_event('retry-lid');value['data']['message']['content']={'text':'@12345678901234 oi'}
        self.assertEqual(await self.adapter.ingest(value,'websocket'),'retry')
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'retry')
        self.adapter.client.own_lid_for.assert_awaited_once()
        self.assertIsNone(self.adapter.inbox.take())
        self.adapter.bot_identity_next=0
        self.adapter.client.own_lid_for.side_effect=None
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        self.assertEqual(await self.adapter.ingest(value,'webhook'),'queued')

    async def test_expired_identity_and_changed_number_never_match_stale_lid(self):
        self.adapter.client.own_lid_for.return_value='12345678901234@lid'
        await self.adapter.refresh_bot_identity()
        msg={'content':{'text':'@12345678901234 oi'}}
        self.assertTrue(self.adapter.group_addressed(msg,GID))
        self.adapter.bot_identity_until=time.monotonic()-1
        self.assertFalse(self.adapter.group_addressed(msg,GID))
        self.adapter.bot_identity_next=0;await self.adapter.refresh_bot_identity()
        self.adapter.set_bot_number('5511777777777')
        self.assertEqual(self.adapter.bot_lid,'')
        self.assertFalse(self.adapter.group_addressed(msg,GID))

    async def test_phone_aliases_and_reply_still_work_without_lid_lookup(self):
        self.adapter.set_bot_number('5511988888888')
        for identifier in ('551188888888','5511988888888','551188888888@s.whatsapp.net'):
            self.assertTrue(self.adapter.group_addressed({'mentions':{'mentionedUsers':[identifier]}},GID))
        self.adapter.telemetry.sent('reply-before-identity',GID)
        self.adapter.set_bot_number('')
        self.assertTrue(self.adapter.group_addressed({'reply':{'message_id':'reply-before-identity'}},GID))
        self.adapter.client.own_lid_for.assert_not_awaited()

class BotIdentityClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        from ryzeapi.client import RyzeClient
        self.calls=[];self.contact={'found':True,'jid':'551188888888@s.whatsapp.net','lid':'12345678901234@lid'}
        self.profile={'jid':'5511988888888@s.whatsapp.net','phoneNumber':'5511988888888','lid':'12345678901234@lid'}
        def route(request):
            self.calls.append((request.method,request.url.path,dict(request.url.params)))
            if request.url.path=='/api/chat/contacts/synthetic-instance':return httpx.Response(200,json={'success':True,'contact':self.contact})
            if request.url.path=='/api/profile/getAccount/synthetic-instance':return httpx.Response(200,json={'success':True,'profile':self.profile})
            raise AssertionError('Unexpected identity endpoint')
        self.client=RyzeClient('synthetic-instance','synthetic-token',transport=httpx.MockTransport(route))
    async def asyncTearDown(self):await self.client.close()
    async def test_contact_uses_configured_phone_and_validated_alias(self):
        self.assertEqual(await self.client.own_lid_for('5511988888888'),'12345678901234@lid')
        self.assertEqual(self.calls,[('GET','/api/chat/contacts/synthetic-instance',{'number':'5511988888888'})])
    async def test_own_profile_fallback_never_looks_up_arbitrary_mention(self):
        self.contact={'found':False}
        self.assertEqual(await self.client.own_lid_for('5511988888888'),'12345678901234@lid')
        self.assertEqual(self.calls[-1],('GET','/api/profile/getAccount/synthetic-instance',{}))
    async def test_mismatch_and_missing_fields_fail_closed(self):
        self.contact={'found':True,'jid':'5511777777777@s.whatsapp.net','lid':'12345678901234@lid'}
        for profile in ({'lid':'12345678901234@lid'}, {'jid':'5511988888888@s.whatsapp.net','phoneNumber':'5511777777777','lid':'12345678901234@lid'}, {'jid':'5511988888888@s.whatsapp.net','lid':'12345678901234'}):
            self.profile=profile
            self.assertEqual(await self.client.own_lid_for('5511988888888'),'')
    async def test_invalid_phone_does_not_call_provider(self):
        self.assertEqual(await self.client.own_lid_for('12345678901234@lid'),'')
        self.assertEqual(self.calls,[])

import test_management as mg
from ryzeapi import management as m, settings

class GroupManagementTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=mg.ManagementTests.asyncSetUp
    asyncTearDown=mg.ManagementTests.asyncTearDown
    setup_selected=mg.ManagementTests.setup_selected
    async def prepare(self):
        await self.setup_selected()
        with GroupStore(settings.directory(),'hermes-test') as store:
            store.sync([{'groupJid':GID,'name':'Grupo teste'}])
    async def test_policy_requires_confirmation_and_matching_instance(self):
        await self.prepare()
        body={'instance':'hermes-test','jid':GID,'mode':'respond','trigger':'all','senders':'all'}
        self.assertEqual((await self.client.post('/groups/policy',json=body)).status_code,400)
        body.update(confirm=True,instance='other')
        self.assertEqual((await self.client.post('/groups/policy',json=body)).status_code,409)
        with GroupStore(settings.directory(),'hermes-test') as store:self.assertEqual(store.policy(GID)['mode'],'blocked')
    async def test_save_and_block_does_not_restart_or_change_contacts(self):
        await self.prepare()
        prior=settings.load()
        async def upstream(token,method,path,**kw):
            self.assertIn(method,('POST','GET'))
            if method=='POST':
                self.assertEqual(path,'/api/instance/settings/hermes-test')
                self.assertEqual(kw['payload'],{'ignoreGroupMessages':False})
            else:self.assertEqual(path,'/api/instance/getSettings/hermes-test')
            return {'success':True,'settings':{'ignoreGroupMessages':False}}
        with patch.object(m,'upstream',side_effect=upstream):
            body={'instance':'hermes-test','jid':GID,'mode':'listen','trigger':'mentions','senders':'authorized','confirm':True}
            self.assertEqual((await self.client.post('/groups/policy',json=body)).status_code,200)
        with GroupStore(settings.directory(),'hermes-test') as reopened:
            self.assertEqual(reopened.policy(GID)['mode'],'listen')
        rows=(await self.client.get('/groups')).json()['groups']
        self.assertEqual(next(row for row in rows if row['jid']==GID)['mode'],'listen')
        self.assertEqual(settings.load(),prior)
        body['mode']='blocked'
        self.assertEqual((await self.client.post('/groups/policy',json=body)).status_code,200)
        self.restart_mock.assert_not_awaited()
    async def test_respond_policy_readback_and_webhook_persist_after_reload(self):
        await self.prepare()
        value=settings.load();value['webhook_configured']=True;value['webhook_secret']='synthetic-hook-secret';settings.save(value)
        prior=settings.load();calls=[]
        async def upstream(token,method,path,**kw):
            calls.append((method,path))
            if (method,path)==('POST','/api/instance/settings/hermes-test'):
                self.assertEqual(kw['payload'],{'ignoreGroupMessages':False})
                return {'success':True}
            if (method,path)==('GET','/api/instance/getSettings/hermes-test'):
                return {'success':True,'settings':{'ignoreGroupMessages':False}}
            if (method,path)==('POST','/api/events/webhook/hermes-test'):
                self.assertEqual(kw['payload']['events'],m.EVENTS)
                return {'success':True}
            if (method,path)==('GET','/api/events/getWebhook/hermes-test'):
                return {'success':True,'webhook':{'events':m.EVENTS}}
            raise AssertionError('Undocumented method/path: '+method+' '+path)
        body={'instance':'hermes-test','jid':GID,'mode':'respond','trigger':'mentions','senders':'all','confirm':True}
        with patch.object(m,'upstream',side_effect=upstream):
            result=await self.client.post('/groups/policy',json=body)
            self.assertEqual(result.status_code,200)
            self.assertTrue(result.json()['saved'])
        self.assertEqual(len(calls),4)
        with GroupStore(settings.directory(),'hermes-test') as reopened:
            policy=reopened.policy(GID)
            for key in ('mode','trigger','senders'):self.assertEqual(policy[key],body[key])
        rows=(await self.client.get('/groups')).json()['groups']
        row=next(row for row in rows if row['jid']==GID)
        for key in ('mode','trigger','senders'):self.assertEqual(row[key],body[key])
        self.assertEqual(settings.load(),prior)
        self.restart_mock.assert_not_awaited()
    async def test_sync_is_explicit_atomic_and_secret_free(self):
        await self.prepare()
        with patch.object(m,'upstream',new=AsyncMock(return_value={'groups':[{'groupJid':OTHER,'name':'Novo','token':'not-browser'}]})) as upstream:
            result=await self.client.post('/groups/sync',json={})
            self.assertEqual(result.status_code,200);self.assertNotIn('not-browser',result.text)
            self.assertEqual(upstream.await_args.args[1:3],('GET','/api/group/list/hermes-test'))
            self.assertTrue(all(row['mode']=='blocked' for row in result.json()['groups']))
        with patch.object(m,'upstream',new=AsyncMock(return_value={'groups':[{'groupJid':'invalid'}]})):
            self.assertEqual((await self.client.post('/groups/sync',json={})).status_code,502)
        self.assertFalse((settings.directory()/'group-conversations').exists())
    async def test_provider_failure_never_grants_access(self):
        await self.prepare()
        with patch.object(m,'upstream',new=AsyncMock(return_value={'settings':{'ignoreGroupMessages':True}})):
            result=await self.client.post('/groups/policy',json={'instance':'hermes-test','jid':GID,'mode':'respond','trigger':'all','senders':'all','confirm':True})
            self.assertEqual(result.status_code,502)
        with GroupStore(settings.directory(),'hermes-test') as store:self.assertEqual(store.policy(GID)['mode'],'blocked')
