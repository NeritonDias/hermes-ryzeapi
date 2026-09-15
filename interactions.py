"""Correlate reply choices without trusting missing/foreign quoted-message metadata."""
import copy, secrets, sqlite3, time
from contextlib import closing

TTL=7*86400

def selection(msg):
    """Catalog and observed 2026-09-15 wire fields; never infer from plain text."""
    kind=msg.get('type')
    value=msg.get('interactive')
    value=value if isinstance(value,dict) else {}
    if kind in ('buttons_response','button_response','template_button_reply'):
        old=msg.get('button_response') or {}
        identifier=value.get('selectedButtonId') or (old.get('selected_button_id') if isinstance(old,dict) else None)
        category='button'
    elif kind=='list_response':
        nested=value.get('selectedReply') or {}
        identifier=value.get('selectedRowId') or (nested.get('selectedRowID') if isinstance(nested,dict) else None)
        category='list'
    else:return None
    return (category,identifier) if isinstance(identifier,str) and 1<=len(identifier)<=2000 else None

class InteractionStore:
    """Private, instance/chat scoped, expiring mappings. Never retain media or tokens."""
    def __init__(self,root,instance):
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        path=root/'interactions.db'
        self.db=sqlite3.connect(path,timeout=10);path.chmod(0o600)
        self.instance=instance
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS choices (wire TEXT PRIMARY KEY, instance TEXT, chat TEXT, category TEXT, logical TEXT, label TEXT, context TEXT, message_id TEXT, created REAL)')
            self.db.execute('DELETE FROM choices WHERE created<?',(time.time()-TTL,))
    def close(self):self.db.close()

    def prepare(self,kind,payload,chat):
        payload=copy.deepcopy(payload);choices=[]
        if kind=='buttons':
            options=[('button',b,b.get('displayText','')) for b in payload.get('buttons',[]) if b.get('type','REPLY')=='REPLY']
        elif kind=='list':
            options=[('list',r,r.get('title','')) for s in payload.get('sections',[]) for r in s.get('rows',[])]
        elif kind=='carousel':
            options=[('button',b,b.get('displayText','')) for c in payload.get('cards',[]) for b in c.get('buttons',[]) if b.get('type','REPLY')=='REPLY']
        else:return payload,choices
        context='\n'.join(str(payload.get(k) or '') for k in ('headerText','contentText','message')).strip()[:4000]
        with self.db:
            for category,option,label in options:
                logical=option['id'];wire='hry_'+secrets.token_hex(16)
                self.db.execute('INSERT INTO choices VALUES (?,?,?,?,?,?,?,NULL,?)',
                    (wire,self.instance,chat,category,logical[:2000],label[:1000],context,time.time()))
                option['id']=wire;choices.append(wire)
        return payload,choices

    def accepted(self,choices,mid):
        if not isinstance(mid,str) or not 1<=len(mid)<=256:raise ValueError('Invalid sent message reference')
        with self.db:
            self.db.executemany('UPDATE choices SET message_id=? WHERE wire=? AND instance=?',[(mid,w,self.instance) for w in choices])

def correlate(root,instance,chat,msg):
    selected=selection(msg)
    if not selected or not selected[1].startswith('hry_'):return msg,False
    path=root/'interactions.db'
    if not path.exists():return msg,False
    with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5)) as db:
        row=db.execute('SELECT logical,label,context,message_id FROM choices WHERE wire=? AND instance=? AND chat=? AND category=? AND created>=? AND message_id IS NOT NULL',
            (selected[1],instance,chat,selected[0],time.time()-TTL)).fetchone()
    if not row:return msg,False
    logical,label,context,mid=row
    reply=msg.get('reply')
    if isinstance(reply,dict) and reply.get('message_id') and reply['message_id']!=mid:return msg,False
    result=dict(msg)
    # Replace wire capability with semantic choice. Never interpret it as a slash command.
    result['content']={'text':'[Resposta interativa — dados do participante]\nOpção: '+label+'\nID da opção: '+logical}
    result['interactive']={}
    result.pop('button_response',None);result.pop('list_response',None)
    result['reply']={'message_id':mid,'text':context}
    return result,True
