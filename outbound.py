"""Typed, plugin-owned message contracts from the official RyzeAPI message docs.

No arbitrary endpoint, credential, destination override or POST retry is exposed.
"""
import copy
import ipaddress
import json
import math
import re
from datetime import datetime
from urllib.parse import urlsplit
from .core import MAX_BODY, validated_base64, phone, lid
from .groups import group_id

def string(description='', limit=4000, minimum=1):
    return dict(type='string',minLength=minimum,maxLength=limit,description=description)
def enum(*values): return dict(type='string',enum=list(values))
def integer(low,high): return dict(type='integer',minimum=low,maximum=high)
def array(items,low=1,high=100): return dict(type='array',items=items,minItems=low,maxItems=high)
def obj(properties,required=()):
    return dict(type='object',properties=properties,required=list(required),additionalProperties=False)
BOOL={'type':'boolean'}
URL=string('Public HTTPS URL. No credentials, localhost or private addresses.',4096)
ID=string('Exact provider message/option identifier; never invent a message ID.',256)
BUTTON=obj({'id':string('REPLY: option ID; URL: HTTPS URL; CALL: international phone; COPY: literal code.'),
            'displayText':string('Visible button label.',100),'type':enum('REPLY','URL','CALL','COPY')},('id','displayText'))
COMMON={'delay':integer(0,30),'replyTo':ID,
        'source':string('Trace label, not a credential.',100)}
HEAD={'headerText':string(),'footerText':string()}
AUDIO={'isVoice':BOOL,'duration':integer(0,4294967295),'waveform':array(integer(0,255),0,1024)}
KINDS={
 'text':(obj({'message':string(limit=32000),'linkPreview':BOOL,
              'mention':array(string(limit=100),0,10),'mentionAll':BOOL},('message',)), 'text'),
 'media':(obj({'mediaType':enum('image','video','audio','document'),'mediaUrl':string(limit=MAX_BODY),
              'mediaBase64':string(limit=MAX_BODY),'message':string(limit=32000,minimum=0),
              'mimeType':string(limit=150),'fileName':string(limit=255),**AUDIO,
              'mention':array(string(limit=100),0,10),'mentionAll':BOOL},('mediaType',)), 'media'),
 'sticker':(obj({'imageUrl':string('Public image URL or data:image/...;base64,...',MAX_BODY)},('imageUrl',)), 'sticker'),
 'contact':(obj({'vcard':array(obj({'fullName':string(limit=300),'phone':string(limit=30),
              'organization':string(limit=300),'email':string(limit=320),'url':URL},('fullName','phone')))},('vcard',)), 'contact'),
 'location':(obj({'latitude':dict(type='number',minimum=-90,maximum=90),
              'longitude':dict(type='number',minimum=-180,maximum=180),'name':string(),'address':string()},
              ('latitude','longitude','name','address')), 'location'),
 'pix':(obj({'merchantName':string(limit=300),'pixKey':string(limit=320),
              'pixKeyType':enum('CPF','CNPJ','EMAIL','PHONE','RANDOM')},('merchantName','pixKey','pixKeyType')), 'pix'),
 'buttons':(obj({'contentText':string(),**HEAD,'buttons':array(BUTTON,1,3),
              'mediaUrl':URL,'mediaType':enum('IMAGE','VIDEO','DOCUMENT')},('contentText','buttons')), 'button'),
 'list':(obj({'contentText':string(),**HEAD,'buttonText':string(limit=100),
              'sections':array(obj({'title':string(limit=300),'rows':array(obj({'id':ID,'title':string(limit=300),
              'description':string()},('id','title')),1,10)},('title','rows')),1,10)},('contentText','buttonText','sections')), 'list'),
 'carousel':(obj({'message':string(),'footer':string(),'cards':array(obj({
              'header':obj({'title':string(),'subtitle':string(),'imageUrl':URL,'videoUrl':URL},('title',)),
              'body':obj({'text':string()},('text',)),'footer':string(),'buttons':array(BUTTON,0,3)},('header','body')),1,10)},('cards',)), 'carousel'),
 'form':(obj({'message':string(),'formType':enum('contact_details','registration_offer'),
              'buttonLabel':string(limit=100),'flowToken':string(limit=256),'flowId':string(limit=100),
              'flowMessageVersion':string(limit=10),'messageVersion':integer(1,100),
              'buttonParamsJSON':string(limit=16000),
              **{k:BOOL for k in ('fullNameVisible','phoneNumberVisible','emailVisible','cpfOrCnpjVisible','deliveryAddressVisible')},
              'offerName':string(),'offerDescription':string()},('message',)), 'form'),
 'poll':(obj({'question':string(),'options':array(string(),2,12),'maxAnswer':integer(1,12)},('question','options')), 'poll'),
 'event':(obj({'name':string(),'startAt':string(limit=40),'endAt':string(limit=40),'description':string(),
              'location':obj({'name':string(),'address':string(),'latitude':dict(type='number',minimum=-90,maximum=90),
              'longitude':dict(type='number',minimum=-180,maximum=180)}),'joinLink':URL,
              'isScheduleCall':BOOL,'hasReminder':BOOL,'reminderOffsetSec':integer(0,31536000),
              'extraGuestsAllowed':BOOL,'isCanceled':BOOL},('name','startAt')), 'event'),
 'reaction':(obj({'messageId':ID,'reaction':string(limit=32),'fromMe':BOOL,'participant':string(limit=100)},('messageId','reaction')), 'reaction'),
 'status':(obj({'type':enum('text','image','video','audio'),'message':string(),'mediaUrl':URL,
              'mimeType':string(limit=150),'fileName':string(limit=255),'backgroundColor':string(limit=9),
              'font':string(limit=50),**AUDIO},('type','message')), 'status'),
}

def payload_schema(kind):
    schema=copy.deepcopy(KINDS[kind][0])
    schema['properties'].update({'source':COMMON['source']} if kind in ('reaction','status') else COMMON)
    return schema

def validate(value,schema,path='payload'):
    kind=schema['type']
    valid={'object':lambda:type(value) is dict,'array':lambda:type(value) is list,
           'string':lambda:type(value) is str,'boolean':lambda:type(value) is bool,
           'integer':lambda:type(value) is int,
           'number':lambda:type(value) in (int,float) and math.isfinite(value)}[kind]()
    if not valid: raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']: raise ValueError(f'{path}: invalid choice')
    if kind=='object':
        if set(value)-schema['properties'].keys(): raise ValueError(f'{path}: unsupported fields')
        if set(schema['required'])-value.keys(): raise ValueError(f'{path}: missing required fields')
        for key,item in value.items():validate(item,schema['properties'][key],path+'.'+key)
    elif kind in ('array','string'):
        low,high=('minItems','maxItems') if kind=='array' else ('minLength','maxLength')
        if not schema.get(low,0)<=len(value)<=schema.get(high,MAX_BODY):raise ValueError(f'{path}: length outside allowed range')
        if kind=='array':
            for i,item in enumerate(value):validate(item,schema['items'],f'{path}[{i}]')
        elif schema.get('minLength',0)>0 and not value.strip():raise ValueError(f'{path}: empty value')
    elif kind in ('integer','number'):
        if not schema.get('minimum',-math.inf)<=value<=schema.get('maximum',math.inf):raise ValueError(f'{path}: out of range')

def public_url(value):
    """Static gate; remote fetches are performed by RyzeAPI, not this plugin."""
    try:
        parsed=urlsplit(value)
        host=(parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme!='https' or not host or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError()
        if any(c.isspace() for c in value) or '\\' in value:raise ValueError()
        if host in ('localhost','metadata.google.internal') or '.' not in host or host.endswith(('.local','.internal','.localhost')):raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:raise ValueError()
        except ValueError:
            if re.fullmatch(r'[0-9.:]+',host) or ':' in host:raise
        return value
    except (ValueError,TypeError):raise ValueError('Expected a public HTTPS URL without credentials') from None

def prepare(kind,payload,number=None):
    if kind not in KINDS:raise ValueError('Unsupported message format')
    validate(payload,payload_schema(kind))
    if len(json.dumps(payload,allow_nan=False).encode())>MAX_BODY:raise ValueError('Payload exceeds plugin limit')
    value=copy.deepcopy(payload)
    if kind!='status':
        if not (phone(number) or group_id(number)):raise ValueError('Explicit phone or group JID required')
        value['number']=group_id(number) or phone(number)
    elif number:raise ValueError('Status is broadcast, not a chat message')
    value.setdefault('source','hermes-ryzeapi')
    if kind in ('text','media'):
        if (value.get('mention') or value.get('mentionAll')) and not group_id(number):raise ValueError('Mentions require a group')
        if any(not (phone(n) or lid(n)) for n in value.get('mention',[])):raise ValueError('Invalid mention identifier')
    if kind=='media':
        sources=[key for key in ('mediaUrl','mediaBase64') if value.get(key)]
        if len(sources)!=1:raise ValueError('Use exactly one mediaUrl or mediaBase64')
        key=sources[0];source=value[key]
        if key=='mediaUrl' and source.startswith('https://'):public_url(source)
        else:
            value.pop(key)
            value['mediaBase64']=validated_base64(source,value.get('mimeType',''))
        if value['mediaType']!='audio' and any(k in value for k in AUDIO):raise ValueError('Audio options require audio media')
        if value['mediaType']=='audio':value.setdefault('isVoice',False)
    if kind=='sticker':
        source=value['imageUrl']
        if source.startswith('data:image/'):
            validated_base64(source,'')
        else:public_url(source)
    if kind=='contact':
        for card in value['vcard']:
            if not phone(card['phone']):raise ValueError('Contact requires international phone')
            if card.get('url'):public_url(card['url'])
    if kind=='location' and value['latitude']==value['longitude']==0:raise ValueError('RyzeAPI rejects location (0,0)')
    if kind=='pix':
        key=value['pixKey'];typ=value['pixKeyType']
        patterns={'CPF':r'[0-9]{11}','CNPJ':r'[0-9]{14}','EMAIL':r'[^\s@]+@[^\s@]+\.[^\s@]+',
                  'PHONE':r'[1-9][0-9]{7,14}','RANDOM':r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}'}
        if not re.fullmatch(patterns[typ],key):raise ValueError('PIX key format does not match key type; use the real user-provided key')
    warnings=[]
    batches=[value['buttons']] if kind=='buttons' else [c.get('buttons',[]) for c in value['cards']] if kind=='carousel' else []
    for buttons in batches:
        if len({b['id'] for b in buttons})!=len(buttons):raise ValueError('Button IDs must be unique per card')
        types={b.get('type','REPLY') for b in buttons}
        if 'REPLY' in types and len(types)>1:warnings.append('Mixed REPLY and URL/CALL/COPY buttons may hide REPLY on WhatsApp Web/Desktop.')
        for button in buttons:
            typ=button.setdefault('type','REPLY')
            if typ=='URL':public_url(button['id'])
            if typ=='CALL' and not re.fullmatch(r'\+[1-9][0-9]{7,14}',button['id']):raise ValueError('CALL requires +international phone')
    if kind=='buttons' and value.get('mediaUrl'):
        public_url(value['mediaUrl'])
        if 'mediaType' not in value:raise ValueError('mediaType required for button media header')
        if value.get('headerText'):warnings.append('Media header replaces headerText.')
    if kind=='carousel':
        for card in value['cards']:
            header=card['header']
            if header.get('imageUrl') and header.get('videoUrl'):raise ValueError('Use only one header media per card')
            for key in ('imageUrl','videoUrl'):
                if header.get(key):public_url(header[key])
    if kind=='list':
        ids=[row['id'] for section in value['sections'] for row in section['rows']]
        if len(set(ids))!=len(ids):raise ValueError('List row IDs must be unique')
    if kind=='poll' and value.get('maxAnswer',1)>len(value['options']):raise ValueError('maxAnswer exceeds option count')
    if kind=='form':
        warnings.append('Native Flow buttons require Android/iOS; not rendered on WhatsApp Web/Desktop.')
        if value.get('buttonParamsJSON'):
            try:params=json.loads(value['buttonParamsJSON'])
            except ValueError:raise ValueError('buttonParamsJSON must contain valid JSON') from None
            if not isinstance(params,dict):raise ValueError('buttonParamsJSON must contain an object')
        # Other flow fields are left to the documented provider contract.
    if kind=='event':
        dates=[]
        for key in ('startAt','endAt'):
            if key not in value:continue
            try:
                stamp=datetime.fromisoformat(value[key].replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError()
            except ValueError:raise ValueError(key+' requires ISO 8601 date/time with timezone') from None
            dates.append(stamp)
        if len(dates)==2 and dates[1]<=dates[0]:raise ValueError('endAt must be later than startAt')
        if value.get('joinLink'):public_url(value['joinLink'])
    if kind=='reaction':
        if group_id(number) and not value.get('fromMe',False) and not (phone(value.get('participant')) or lid(value.get('participant'))):
            raise ValueError('Group reaction requires the original author participant JID')
    if kind=='status':
        if value['type']!='text':
            if not value.get('mediaUrl'):raise ValueError('mediaUrl required for media status')
            public_url(value['mediaUrl'])
        if value.get('backgroundColor') and not re.fullmatch(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?',value['backgroundColor']):raise ValueError('Invalid status color')
        warnings.append('Status is visible for 24h to the audience configured in WhatsApp, outside the contact firewall.')
    return value,list(dict.fromkeys(warnings))
