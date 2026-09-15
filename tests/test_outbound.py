"""All official message routes, with synthetic identities and mocked transport."""
import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
import test_ryzeapi as original
from test_ryzeapi import OWNER
from ryzeapi.outbound import KINDS,prepare,public_url
from ryzeapi.client import RyzeClient,RyzeError
from ryzeapi.tools import execute,handle,register_tools,SendLedger
from ryzeapi.groups import GroupStore

GID='120363000000000001@g.us'
FIXTURES={
 'text':{'message':'Test'},
 'media':{'mediaType':'image','mediaUrl':'https://example.com/image.png'},
 'sticker':{'imageUrl':'data:image/png;base64,aGVsbG8='},
 'contact':{'vcard':[{'fullName':'Synthetic Contact','phone':OWNER}]},
 'location':{'latitude':-23.5,'longitude':-46.6,'name':'Public place','address':'Public street'},
 'pix':{'merchantName':'Synthetic — do not pay','pixKey':'example@example.com','pixKeyType':'EMAIL'},
 'buttons':{'contentText':'Choose','buttons':[{'id':'yes','displayText':'Yes'}]},
 'list':{'contentText':'Choose','buttonText':'Open','sections':[{'title':'Options','rows':[{'id':'yes','title':'Yes'}]}]},
 'carousel':{'cards':[{'header':{'title':'Card'},'body':{'text':'Description'},'buttons':[{'id':'yes','displayText':'Yes'}]}]},
 'form':{'message':'Fill in','formType':'contact_details','cpfOrCnpjVisible':False},
 'poll':{'question':'Choose','options':['A','B']},
 'event':{'name':'Synthetic event','startAt':'2027-01-01T12:00:00-03:00'},
 'reaction':{'messageId':'synthetic-message','reaction':'👍','fromMe':True},
 'status':{'type':'text','message':'Synthetic, never published','backgroundColor':'#008877'},
}

class ContractTests(unittest.TestCase):
    def test_all_fourteen_formats_and_no_input_mutation(self):
        self.assertEqual(set(FIXTURES),set(KINDS));self.assertEqual(len(KINDS),14)
        for kind,value in FIXTURES.items():
            with self.subTest(kind=kind):
                before=copy.deepcopy(value)
                body,_=prepare(kind,value,None if kind=='status' else GID)
                self.assertEqual(value,before)
                self.assertEqual(body.get('number'),None if kind=='status' else GID)
                self.assertEqual(body['source'],'hermes-ryzeapi')

    def test_invalid_fields_and_types_fail_closed(self):
        for kind,value in FIXTURES.items():
            for extra in ({'token':'SECRET'},{'number':OWNER},{'replyPrivate':True},{'endpoint':'/admin'},{'source':None}):
                with self.subTest(kind=kind,extra=extra):
                    with self.assertRaises(ValueError):prepare(kind,dict(value,**extra),None if kind=='status' else GID)
        for value in (None,[],True,'payload'):
            with self.assertRaises(ValueError):prepare('text',value,OWNER)
        with self.assertRaises(ValueError):prepare('text',{'message':'x','delay':True},OWNER)

    def test_button_and_list_limits(self):
        for count in (0,4):
            with self.assertRaises(ValueError):prepare('buttons',{'contentText':'x','buttons':[{'id':str(i),'displayText':'X'} for i in range(count)]},OWNER)
        for sections in ([],[{'title':'x','rows':[{'id':str(i),'title':'x'} for i in range(11)]}],
                         [{'title':'x','rows':[{'id':'x','title':'x'}]}]*11):
            with self.assertRaises(ValueError):prepare('list',{'contentText':'x','buttonText':'x','sections':sections},OWNER)

    def test_all_button_types_and_client_warning(self):
        for typ,identifier in [('REPLY','reply-id'),('URL','https://example.com'),('CALL','+5511999999999'),('COPY','CODE')]:
            body,_=prepare('buttons',{'contentText':'x','buttons':[{'id':identifier,'displayText':'X','type':typ}]},OWNER)
            self.assertEqual(body['buttons'][0]['type'],typ)
        _,warnings=prepare('buttons',{'contentText':'x','buttons':[{'id':'yes','displayText':'Yes'},
            {'id':'https://example.com','displayText':'Open','type':'URL'}]},OWNER)
        self.assertTrue(warnings)

    def test_public_url_gate(self):
        for url in ('http://example.com/a','https://127.0.0.1/a','https://169.254.169.254/a',
                    'https://10.0.0.1','https://[::1]','https://localhost','https://internal.local',
                    'https://user:secret@example.com','file:///etc/passwd','https://example.com:8080',
                    'https://example.com\\@127.0.0.1'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):public_url(url)
        self.assertEqual(public_url('https://example.com/a'),'https://example.com/a')

    def test_format_specific_cross_fields(self):
        invalid=[('media',{'mediaType':'image','mediaUrl':'https://example.com','mediaBase64':'aGVsbG8='}),
                 ('media',{'mediaType':'image'}),('media',{'mediaType':'audio','mediaBase64':'!!!'}),
                 ('buttons',{'contentText':'x','buttons':[{'id':'x','displayText':'x'}],'mediaUrl':'https://example.com'}),
                 ('poll',{'question':'x','options':['a']}),('poll',{'question':'x','options':['a','b'],'maxAnswer':3}),
                 ('event',{'name':'x','startAt':'2027-01-01T12:00:00'}),
                 ('event',{'name':'x','startAt':'2027-01-02T12:00:00Z','endAt':'2027-01-01T12:00:00Z'}),
                 ('location',dict(FIXTURES['location'],latitude=float('nan'))),
                 ('location',dict(FIXTURES['location'],latitude=0,longitude=0)),
                 ('pix',dict(FIXTURES['pix'],pixKeyType='CPF')),
                 ('reaction',{'messageId':'x','reaction':'👍'}),
                 ('form',dict(FIXTURES['form'],buttonParamsJSON='[]')),
                 ('status',{'type':'image','message':'x'})]
        for kind,value in invalid:
            with self.subTest(kind=kind,value=value):
                with self.assertRaises(ValueError):prepare(kind,value,None if kind=='status' else GID)

    def test_reaction_participant_and_media_base64(self):
        body,_=prepare('reaction',dict(FIXTURES['reaction'],fromMe=False,participant=OWNER+'@s.whatsapp.net'),GID)
        self.assertFalse(body['fromMe'])
        body,_=prepare('media',{'mediaType':'audio','mediaBase64':'aGVsbG8='},OWNER)
        self.assertIs(body['isVoice'],False)

class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_routes_bodies_headers_and_safe_results(self):
        for kind,payload in FIXTURES.items():
            requests=[]
            def transport(request):
                requests.append(request)
                return httpx.Response(200,json={'success':True,'status':'sent','data':{'messageId':'provider-id','content':'SECRET-CONTENT'}})
            client=RyzeClient('test-instance','SECRET-TOKEN',transport=httpx.MockTransport(transport))
            try:result=await client.send_rich(kind,None if kind=='status' else GID,payload)
            finally:await client.close()
            self.assertEqual(len(requests),1)
            self.assertEqual(requests[0].method,'POST')
            self.assertEqual(requests[0].url.path,f'/api/message/{KINDS[kind][1]}/test-instance')
            self.assertEqual(requests[0].headers['token'],'SECRET-TOKEN')
            self.assertNotIn('SECRET',json.dumps(result))
            self.assertFalse(result['delivered'])
            self.assertEqual(json.loads(requests[0].content),prepare(kind,payload,None if kind=='status' else GID)[0])

    async def test_sends_never_retry_or_claim_unconfirmed_success(self):
        for mode in ('timeout','500','429','noid','false','not_sent'):
            calls=[]
            def transport(request):
                calls.append(request)
                if mode=='timeout':raise httpx.ReadTimeout('SECRET',request=request)
                if mode in ('500','429'):return httpx.Response(int(mode),text='SECRET')
                return httpx.Response(200,json={'success':mode!='false','status':'disconnected' if mode=='not_sent' else 'sent',
                    'data':{} if mode=='noid' else {'messageId':'id'}})
            client=RyzeClient('test-instance','SECRET',transport=httpx.MockTransport(transport))
            try:
                with self.assertRaises(RyzeError) as error:await client.send_rich('buttons',OWNER,FIXTURES['buttons'])
                self.assertNotIn('SECRET',str(error.exception));self.assertEqual(len(calls),1)
            finally:await client.close()

class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await original.AdapterTests.asyncSetUp(self)
        self.adapter.allowed_raw=self.adapter.recipients_raw=OWNER
        self.adapter.token='SYNTHETIC-INSTANCE-TOKEN'
        self.root=Path(self.temp.name)/'ryzeapi'
        self.folder_patch=patch('ryzeapi.tools.directory',return_value=self.root);self.folder_patch.start()
        self.adapter.group_store=GroupStore(self.root,'hermes-test')
        self.adapter.group_store.sync([{'groupJid':GID,'name':'Synthetic group'}])
        self.adapter.group_store.configure(GID,'respond','mentions','all')
        self.factory_patch=patch('ryzeapi.adapter.RyzeAdapter',return_value=self.adapter);self.factory_patch.start()
        self.client=AsyncMock();self.client.send_rich.return_value={'success':True,'message_id':'sent-tool','status':'accepted','delivered':False}
        self.client_patch=patch('ryzeapi.tools.RyzeClient',return_value=self.client);self.client_patch.start()
        self.origin={'platform':'ryzeapi','chat':GID,'type':'group','user':OWNER}
    async def asyncTearDown(self):
        self.client_patch.stop();self.factory_patch.stop();self.folder_patch.stop()
        await original.AdapterTests.asyncTearDown(self)
    def args(self,**kwargs):return dict(payload=copy.deepcopy(FIXTURES['buttons']),number=GID,request_id='test-operation',**kwargs)

    async def test_actual_tool_dispatch_and_durable_dedup(self):
        result=await execute('buttons',self.args(),origin=self.origin)
        self.assertTrue(result['success'])
        wire=self.client.send_rich.call_args.args[2]['buttons'][0]['id']
        self.assertTrue(wire.startswith('hry_'));self.assertNotEqual(wire,'yes')
        from ryzeapi.interactions import correlate
        decoded,matched=correlate(self.root,'hermes-test',GID,
            {'type':'buttons_response','interactive':{'selectedButtonId':wire}})
        self.assertTrue(matched);self.assertIn('Yes',decoded['content']['text'])
        self.assertEqual(decoded['reply']['message_id'],'sent-tool')
        result=await execute('buttons',self.args(),origin=self.origin)
        self.assertTrue(result['reused']);self.client.send_rich.assert_awaited_once()
        self.assertNotIn('Choose',(self.root/'outbound.db').read_bytes().decode('latin1'))

    async def test_dry_run_does_not_call_provider(self):
        result=await execute('buttons',self.args(dry_run=True),origin=self.origin)
        self.assertEqual(result['status'],'validated');self.client.send_rich.assert_not_awaited()
        self.assertFalse((self.root/'outbound.db').exists())
        self.assertFalse((self.root/'interactions.db').exists())

    async def test_group_cannot_send_to_dm_or_publish_status(self):
        args=self.args();args['number']=OWNER
        with self.assertRaises(ValueError):await execute('buttons',args,origin=self.origin)
        with self.assertRaises(ValueError):await execute('status',{'payload':FIXTURES['status'],'request_id':'status-test','confirm_status_broadcast':True},origin=self.origin)
        self.client.send_rich.assert_not_awaited()

    async def test_status_requires_approval_and_uses_no_number(self):
        origin={'platform':'ryzeapi','chat':OWNER,'user':OWNER,'type':'dm'}
        args={'payload':FIXTURES['status'],'request_id':'status-test','confirm_status_broadcast':False}
        with self.assertRaises(ValueError):await execute('status',args,origin=origin)
        args['confirm_status_broadcast']=True
        self.assertTrue((await execute('status',args,origin=origin))['success'])
        self.client.send_rich.assert_awaited_once_with('status',None,FIXTURES['status'])

    async def test_unknown_reference_and_revoked_group_blocked(self):
        args=self.args();args['payload']['replyTo']='foreign-message'
        with self.assertRaises(ValueError):await execute('buttons',args,origin=self.origin)
        with GroupStore(self.root,'hermes-test') as store:store.configure(GID,'listen','mentions','all')
        with self.assertRaises(ValueError):await execute('buttons',self.args(),origin=self.origin)
        self.client.send_rich.assert_not_awaited()

    async def test_uncertain_call_is_not_replayed(self):
        self.client.send_rich.side_effect=RyzeError('timeout; uncertain')
        self.assertFalse((await execute('buttons',self.args(),origin=self.origin))['success'])
        result=await execute('buttons',self.args(),origin=self.origin)
        self.assertEqual(result['status'],'uncertain');self.client.send_rich.assert_awaited_once()

    async def test_request_id_cannot_be_reused_for_different_content(self):
        await execute('buttons',self.args(),origin=self.origin)
        args=self.args();args['payload']['contentText']='Different'
        with self.assertRaises(ValueError):await execute('buttons',args,origin=self.origin)
        self.client.send_rich.assert_awaited_once()

    async def test_registration_exposes_all_tools_with_schemas(self):
        class Context:
            def __init__(self):self.entries=[]
            def register_tool(self,**entry):self.entries.append(entry)
        ctx=Context();register_tools(ctx)
        self.assertEqual({e['name'] for e in ctx.entries},{'ryzeapi_send_'+k for k in KINDS})
        self.assertTrue(all(e['is_async'] and e['toolset']=='ryzeapi' for e in ctx.entries))

    async def test_local_media_is_bounded_and_encoded(self):
        image=Path(self.temp.name)/'synthetic.png'
        image.write_bytes(b'synthetic-image')
        args={'payload':{'mediaType':'image'},'number':GID,'request_id':'local-media','file_path':str(image)}
        result=await execute('media',args,origin=self.origin)
        self.assertTrue(result['success'])
        body=self.client.send_rich.call_args.args[2]
        self.assertEqual(body['fileName'],'synthetic.png');self.assertEqual(body['mimeType'],'image/png')
        self.assertIn('mediaBase64',body)

    async def test_interactive_return_fields_are_bounded(self):
        from ryzeapi.core import structured_text
        text=structured_text({'interactive':{'selectedButtonId':'yes','selectedCarouselCardIndex':1,'token':'SECRET'},
                              'poll':{'title':'Choose','options':[{'name':'A'}]}})
        self.assertIn('yes',text);self.assertIn('card: 1',text);self.assertIn('Choose',text)
        self.assertNotIn('SECRET',text)
