"""Instance-scoped group policy and passive archive. No agent execution here."""
import hashlib, json, os, re, sqlite3, tempfile, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .core import canonical_envelope, phone, lid, structured_text

MODES = {'blocked', 'listen', 'respond'}
TRIGGERS = {'mentions', 'all'}

def group_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9]{5,25}(?:-[0-9]{5,20})?@g\.us', value) else ''

def short(value, size=200):
    return value[:size] if isinstance(value, str) else ''

def member(value):
    value = value if isinstance(value, dict) else {}
    jid = phone(value.get('jid')) or lid(value.get('jid'))
    return {'id': short(value.get('jid'),100) if jid else '', 'number': phone(value.get('jid')), 'lid': lid(value.get('lid')),
            'name': short(value.get('name'))}

class GroupStore:
    def __init__(self, root, instance):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',instance or ''): raise ValueError('Invalid instance')
        self.root, self.instance = root, instance
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / 'groups.db'
        self.db = sqlite3.connect(self.path, timeout=10)
        self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS groups (instance TEXT, jid TEXT, name TEXT, members INTEGER, present INTEGER DEFAULT 1, synced REAL, mode TEXT DEFAULT "blocked", trigger TEXT DEFAULT "mentions", PRIMARY KEY(instance,jid))')
            self.db.execute('CREATE TABLE IF NOT EXISTS group_archive (instance TEXT, jid TEXT, key TEXT, day TEXT, record TEXT, PRIMARY KEY(instance,jid,key))')
            self.db.execute('CREATE INDEX IF NOT EXISTS group_archive_day ON group_archive(instance,jid,day)')
            if 'senders' not in {r[1] for r in self.db.execute('PRAGMA table_info(groups)')}:
                self.db.execute('ALTER TABLE groups ADD COLUMN senders TEXT DEFAULT "authorized"')

    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def list(self):
        return [dict(row) for row in self.db.execute('SELECT jid,name,members,present,synced,mode,trigger,senders FROM groups WHERE instance=? ORDER BY name COLLATE NOCASE,jid', (self.instance,))]

    def policy(self, jid):
        row = self.db.execute('SELECT * FROM groups WHERE instance=? AND jid=?', (self.instance,jid)).fetchone()
        return dict(row) if row else {'mode':'blocked','trigger':'mentions','present':0}

    def sync(self, items):
        # Validate the full snapshot before marking anything absent; partial failures keep policies.
        if not isinstance(items,list) or len(items)>10000: raise ValueError('Invalid group list')
        rows, seen = [], set()
        for item in items:
            if not isinstance(item,dict) or not group_id(item.get('groupJid')): raise ValueError('Invalid group identity')
            jid = item['groupJid']
            if jid in seen: raise ValueError('Duplicate group identity')
            seen.add(jid)
            count = item.get('memberCount')
            if type(count) is not int or not 0<=count<=100000: count = None
            rows.append((self.instance,jid,short(item.get('name')) or jid,count,time.time()))
        with self.db:
            self.db.execute('UPDATE groups SET present=0 WHERE instance=?',(self.instance,))
            self.db.executemany('INSERT INTO groups(instance,jid,name,members,synced) VALUES (?,?,?,?,?) ON CONFLICT(instance,jid) DO UPDATE SET name=excluded.name,members=excluded.members,synced=excluded.synced,present=1',rows)
        return self.list()

    def configure(self, jid, mode, trigger, senders='authorized'):
        if not group_id(jid) or mode not in MODES or trigger not in TRIGGERS or senders not in {'authorized','all'}: raise ValueError('Invalid group policy')
        value = self.policy(jid)
        if not value.get('present') and mode!='blocked': raise ValueError('Synchronize this group first')
        with self.db:
            result = self.db.execute('UPDATE groups SET mode=?,trigger=?,senders=? WHERE instance=? AND jid=?',(mode,trigger,senders,self.instance,jid))
            if not result.rowcount: raise ValueError('Unknown group')
        return self.policy(jid)

    def record(self, payload):
        """Return (vetted record, fresh). Never persist tokens, URLs or raw envelopes."""
        value = canonical_envelope(payload)
        if not isinstance(value,dict) or (value.get('instanceData') or {}).get('instance')!=self.instance: return None, False
        event, data = value.get('event'), value.get('data')
        if not isinstance(data,dict): return None,False
        if event=='message.exchange':
            msg = data.get('message')
            if not isinstance(msg,dict): return None,False
            chat = msg.get('chat') or {}
            jid = group_id(chat.get('jid'))
            if chat.get('type')!='group' or chat.get('isCommunity') or msg.get('direction') not in {'incoming','outgoing'}: return None,False
            mid = short(msg.get('id'),256)
            if not mid: return None,False
            author = member(msg.get('sender'))
            if not author['id']: return None,False
            content = msg.get('content') or {}
            media = msg.get('media') or {}
            if not isinstance(content,dict) or not isinstance(media,dict): return None,False
            text=short(content.get('text'),32000)
            extra=structured_text(msg)
            if extra: text=(text+'\n'+extra).strip()[:32000]
            reply=msg.get('reply')
            record = {'kind':'message','id':mid,'direction':msg['direction'],'member':author,
                      'text':text,'message_type':short(msg.get('type'),50),
                      'reply_id':short(reply.get('message_id'),256) if isinstance(reply,dict) else '',
                      'attachment': {'type':short(media.get('type'),30),'name':short(media.get('fileName')),
                          'mime':short(media.get('mimetype'),100),'caption':short(media.get('caption'),32000)} if media else None}
            stamp = msg.get('timestamp')
            key = 'message:'+mid
        elif event=='group.flow':
            jid = group_id(data.get('groupJid'))
            kind = data.get('type')
            if kind not in {'joined','left','promoted','demoted','name','delete'}: return None,False
            people = data.get('participants',[])
            if not isinstance(people,list) or len(people)>10000: return None,False
            record = {'kind':kind,'members':[member(p) for p in people], 'name':short(data.get('groupName'))}
            stamp = data.get('timestamp')
            key = 'flow:'+hashlib.sha256(json.dumps([jid,kind,stamp,record['members']],sort_keys=True).encode()).hexdigest()
        else: return None,False
        policy = self.policy(jid)
        if not jid or not policy.get('present') or policy['mode']=='blocked': return None,False
        try:
            dt = datetime.fromisoformat(str(stamp).replace('Z','+00:00'))
            if dt.tzinfo is None or not -300 <= time.time()-dt.timestamp() <= 86400: return None,False
        except (ValueError,TypeError): return None,False
        record.update(group_id=jid, group_name=policy['name'], timestamp=dt.isoformat(),
                      received_at=datetime.now(timezone.utc).isoformat())
        day = dt.astimezone(ZoneInfo('America/Sao_Paulo')).date().isoformat()
        with self.db:
            fresh = self.db.execute('INSERT OR IGNORE INTO group_archive VALUES (?,?,?,?,?)',
                (self.instance,jid,key,day,json.dumps(record,ensure_ascii=False))).rowcount>0
            if record['kind']=='name' and record['name']:
                self.db.execute('UPDATE groups SET name=? WHERE instance=? AND jid=?',(record['name'],self.instance,jid))
            if record['kind']=='delete':
                self.db.execute('UPDATE groups SET present=0,mode="blocked" WHERE instance=? AND jid=?',(self.instance,jid))
        # Regenerated atomic per-event files avoid duplicate JSONL lines and repair a failed export on retry.
        saved = self.db.execute('SELECT record FROM group_archive WHERE instance=? AND jid=? AND key=?',(self.instance,jid,key)).fetchone()[0]
        folder = self.root / 'group-conversations' / self.instance / jid / day
        parent = self.root
        for segment in ('group-conversations',self.instance,jid,day):
            parent = parent / segment
            parent.mkdir(mode=0o700,exist_ok=True)
        path = folder / (hashlib.sha256(key.encode()).hexdigest()+'.json')
        fd, temporary = tempfile.mkstemp(prefix='.record-',dir=folder)
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(saved+'\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return json.loads(saved), fresh
