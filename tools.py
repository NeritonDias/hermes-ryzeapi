"""Native Hermes plugin tools. Credentials are never arguments or model results."""
import asyncio
import base64
import functools
import hashlib
import json
import mimetypes
import sqlite3
import time
from pathlib import Path
from .outbound import KINDS, payload_schema, prepare, obj, string, BOOL, validate
from .settings import configured, directory
from .core import allowed_numbers, authorized_phone, MAX_MEDIA
from .groups import GroupStore, group_id
from .client import RyzeClient, RyzeError
from .interactions import InteractionStore

DESCRIPTIONS={
 'text':'Send WhatsApp text with optional link preview and group mentions.',
 'media':'Send a real image/video/audio/document from public URL, base64, or an explicitly selected local file_path (up to 8 MiB).',
 'sticker':'Send a real sticker from public image URL or image data URI.',
 'contact':'Send one or more real contact cards, using user-provided contact details.',
 'location':'Send a real static map/location card with coordinates, name and address.',
 'pix':'Send a visual copy-PIX-key card using the real user-provided beneficiary/key. Does NOT make a payment or create a charge.',
 'buttons':'Send REAL interactive WhatsApp buttons (1–3 REPLY/URL/CALL/COPY), not a numbered text imitation.',
 'list':'Send a REAL selectable WhatsApp list (up to 10 sections × 10 rows).',
 'carousel':'Send a real swipeable carousel (1–10 cards, optional media and buttons).',
 'form':'Send a Native Flow form. Only rendered on Android/iOS, not Web/Desktop.',
 'poll':'Send a REAL WhatsApp poll (2–12 options, single/multiple choice).',
 'event':'Send a real WhatsApp calendar/event card. startAt/endAt need timezone.',
 'reaction':'React to an exact known message ID; use reaction=remove to remove. Incoming group messages need participant JID.',
 'status':'Publish a 24h WhatsApp Status to the app-configured audience, NOT the contact firewall. Requires explicit user approval of content and audience; never from a group session.',
}

def schema(kind):
    properties={'payload':payload_schema(kind),'request_id':string('Unique operation ID (UUID recommended). Reuse only to check the SAME send, never change its payload.',100),
                'dry_run':{**BOOL,'description':'Validate without sending. No external API call.'}}
    required=['payload','request_id']
    if kind=='status':
        properties['confirm_status_broadcast']={**BOOL,'description':'Set true ONLY after the user explicitly approves this content for the WhatsApp Status audience.'}
        required.append('confirm_status_broadcast')
    else:properties['number']=string('Recipient phone or full group JID. Omit only to reply in the current RyzeAPI chat.',100)
    if kind in ('media','sticker'):
        properties['file_path']=string('Local attachment explicitly requested/selected by the user. Do not send credentials or private configuration files.',4096)
        if kind=='sticker':properties['payload']['required']=[]
    return {'name':'ryzeapi_send_'+kind,'description':DESCRIPTIONS[kind]+' Respects the plugin firewall. Never auto-retry an uncertain send.',
            'parameters':obj(properties,required)}

def session_origin():
    from gateway.session_context import get_session_env
    return {key:get_session_env('HERMES_SESSION_'+field,'') for key,field in
            [('platform','PLATFORM'),('chat','CHAT_ID'),('type','CHAT_TYPE'),('user','USER_ID')]}

def authorize(adapter,kind,number,origin,confirmed=False):
    if not adapter.current():raise ValueError('RyzeAPI paused or configuration changed')
    if kind=='status':
        if not confirmed:raise ValueError('Explicit approval of Status content and WhatsApp audience required')
        if group_id(origin.get('chat')) or origin.get('type')=='group':raise ValueError('Status publication is not allowed from group sessions')
        if origin.get('platform')=='ryzeapi' and not authorized_phone(origin.get('user'),adapter.allowed):
            raise ValueError('Only an authorized private operator may publish Status')
        if origin.get('platform') not in ('','local','cli','web','dashboard','api','ryzeapi'):
            raise ValueError('Publish Status from the trusted local panel or authorized private RyzeAPI chat')
        return 'status@broadcast'
    target=adapter.destination(number)
    if not target:raise ValueError('Destination blocked by RyzeAPI firewall')
    if origin.get('platform')=='ryzeapi':
        chat=origin.get('chat','');user=origin.get('user','')
        if group_id(chat):
            policy=adapter.group_policy(chat)
            if target!=chat or not policy.get('present') or policy.get('mode')!='respond':
                raise ValueError('Group tools may send only into their currently authorized group')
            if policy.get('senders')!='all' and not authorized_phone(user,adapter.allowed):
                raise ValueError('Group sender no longer authorized')
        elif not authorized_phone(user,adapter.allowed):raise ValueError('Private sender is not an authorized operator')
    return target

def known_reference(adapter,mid,number):
    """Never quote/react across chats just because the ID belongs to this account."""
    from hermes_constants import get_hermes_home
    path=get_hermes_home()/('ryzeapi-inbox-'+hashlib.sha256(adapter.instance.encode()).hexdigest()[:16]+'.db')
    if path.exists():
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
            if db.execute('SELECT 1 FROM inbox WHERE id=? AND number=?',(mid,number)).fetchone():return True
            if db.execute('SELECT 1 FROM ryze_sent WHERE id=? AND number=?',(mid,number)).fetchone():return True
    if group_id(number):
        return bool(adapter.group_store.db.execute('SELECT 1 FROM group_archive WHERE instance=? AND jid=? AND key=?',
                    (adapter.instance,number,'message:'+mid)).fetchone())
    return False

class SendLedger:
    """An uncertain/crashed operation is never automatically replayed. No content stored."""
    def __init__(self,instance,request_id,kind,number,payload):
        directory().mkdir(mode=0o700,parents=True,exist_ok=True)
        path=directory()/'outbound.db'
        self.db=sqlite3.connect(path,timeout=10)
        path.chmod(0o600)
        self.key=hashlib.sha256((instance+'\0'+request_id).encode()).hexdigest()
        self.digest=hashlib.sha256(json.dumps([kind,number,payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS operations (key TEXT PRIMARY KEY, digest TEXT, state TEXT, result TEXT, created REAL)')
            self.db.execute('DELETE FROM operations WHERE created<?',(time.time()-30*86400,))
    def claim(self):
        with self.db:
            inserted=self.db.execute('INSERT OR IGNORE INTO operations VALUES (?,?,?,NULL,?)',
                (self.key,self.digest,'uncertain',time.time())).rowcount
            if inserted:return None
            digest,state,result=self.db.execute('SELECT digest,state,result FROM operations WHERE key=?',(self.key,)).fetchone()
        if digest!=self.digest:raise ValueError('request_id already belongs to a different operation')
        if state=='accepted':return dict(json.loads(result),reused=True)
        return {'success':False,'status':'uncertain','retry_safe':False,'error':'Operation already attempted or in progress. Verify WhatsApp; it will not be resent.'}
    def finish(self,result):
        with self.db:self.db.execute('UPDATE operations SET state=?,result=? WHERE key=?',('accepted',json.dumps(result),self.key))
    def close(self):self.db.close()

async def execute(kind,args,*,origin=None):
    from gateway.config import PlatformConfig
    from .adapter import RyzeAdapter
    validate(args,schema(kind)['parameters'],'arguments')
    origin=session_origin() if origin is None else origin
    number=args.get('number') or (origin.get('chat') if origin.get('platform')=='ryzeapi' else None)
    if kind=='status':number=None
    adapter=RyzeAdapter(PlatformConfig())
    ledger=None;interactions=None
    try:
        adapter.allowed=allowed_numbers(adapter.allowed_raw)
        adapter.recipients=allowed_numbers(adapter.recipients_raw)
        adapter.group_store=GroupStore(directory(),adapter.instance)
        target=authorize(adapter,kind,number,origin,args.get('confirm_status_broadcast') is True)
        payload=dict(args['payload'])
        if args.get('file_path'):
            if any(k in payload for k in ('mediaUrl','mediaBase64','imageUrl')):raise ValueError('Choose file_path OR URL/base64, not both')
            path=Path(args['file_path']).expanduser().resolve()
            if not path.is_file() or not 0<path.stat().st_size<=MAX_MEDIA:raise ValueError('Local attachment missing or exceeds 8 MiB')
            if any(part in ('.ssh','.oci','.aws') for part in path.parts) or path.name in ('.env','settings.json','auth.json','config.yaml'):
                raise ValueError('Credential/configuration files cannot be sent as attachments')
            def read_bounded():
                with path.open('rb') as stream:return stream.read(MAX_MEDIA+1)
            raw=await asyncio.to_thread(read_bounded)
            if not raw or len(raw)>MAX_MEDIA:raise ValueError('Invalid attachment size')
            mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            encoded=base64.b64encode(raw).decode()
            if kind=='sticker':
                if not mime.startswith('image/'):raise ValueError('Sticker attachment must be an image')
                payload['imageUrl']='data:'+mime+';base64,'+encoded
            else:
                payload.update(mediaBase64=encoded)
                payload.setdefault('mimeType',mime);payload.setdefault('fileName',path.name)
        body,warnings=prepare(kind,payload,None if kind=='status' else target)
        for key in ('replyTo','messageId'):
            if body.get(key) and not known_reference(adapter,body[key],target):raise ValueError('Referenced message is not known in this destination; use the correct chat/message ID')
        if args.get('dry_run'):
            return {'success':True,'status':'validated','sent':False,'format':kind,'warnings':warnings}
        # Revalidate after reading references; never alter group policy or permit private redirection.
        authorize(adapter,kind,number,origin,args.get('confirm_status_broadcast') is True)
        ledger=SendLedger(adapter.instance,args['request_id'],kind,target,body)
        previous=ledger.claim()
        if previous:return previous
        wire_payload=payload;choices=[]
        if kind in ('buttons','list','carousel'):
            interactions=InteractionStore(directory(),adapter.instance)
            wire_payload,choices=interactions.prepare(kind,payload,target)
        adapter.client=RyzeClient(adapter.instance,adapter.token)
        result=await adapter.client.send_rich(kind,None if kind=='status' else target,wire_payload)
        if interactions:interactions.accepted(choices,result['message_id'])
        ledger.finish(result)
        if kind!='status':adapter.record_sent(result['message_id'],target)
        return result
    except RyzeError as exc:
        return {'success':False,'status':'unconfirmed','retry_safe':False,'error':str(exc)}
    except (ValueError,TypeError,KeyError,sqlite3.Error,OSError):
        # Validation errors are returned by the outer handler without secrets;
        # storage/OS details are not useful to the model and can contain paths.
        raise
    finally:
        if interactions:interactions.close()
        if ledger:ledger.close()
        if adapter.client:await adapter.client.close()
        if adapter.group_store:adapter.group_store.close()

async def handle(kind,args,**kwargs):
    try:result=await execute(kind,args)
    except ValueError as exc:result={'success':False,'status':'rejected','error':str(exc)}
    except Exception:result={'success':False,'status':'unconfirmed','retry_safe':False,'error':'RyzeAPI tool unavailable; inspect private plugin diagnostics, do not blindly repeat sends.'}
    return json.dumps(result,ensure_ascii=False)

def register_tools(ctx):
    from .skill_install import register_skills
    register_skills(ctx)
    for kind in KINDS:
        ctx.register_tool(name='ryzeapi_send_'+kind,toolset='ryzeapi',schema=schema(kind),
                          handler=functools.partial(handle,kind),is_async=True,check_fn=configured,emoji='📱')
