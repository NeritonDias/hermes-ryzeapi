"""Private, content-free delivery ledger; receipts are observations, never retries."""
import hashlib, time
from datetime import datetime
from .core import authorized_phone

EVENTS = ['message.exchange', 'instance.state', 'message.status', 'group.flow']
STATES = {'connected','disconnected','logged_out','stream_replaced','temp_banned','client_outdated',
          'connect_failure','stream_error','cat_refresh_error','qr_ready','pair_success','pair_error',
          'qr_scanned_no_multidevice','keepalive_timeout','keepalive_restored','manual_reconnect','connecting','unknown'}
RANK = {'accepted':0,'delivered':1,'read':2,'played':3}
ERRORS = {'retry','inactive','server_error'}

class Telemetry:
    def __init__(self, db):
        self.db = db
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS ryze_sent (id TEXT PRIMARY KEY,number TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS ryze_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1),state TEXT NOT NULL,observed REAL NOT NULL,stamp REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS ryze_early_receipts (id TEXT,number TEXT,state TEXT,stamp REAL,expires REAL,PRIMARY KEY(id,number))')
            db.execute('CREATE INDEX IF NOT EXISTS ryze_early_expiry ON ryze_early_receipts(expires)')
            db.execute('CREATE TABLE IF NOT EXISTS ryze_receipt_checks (id TEXT PRIMARY KEY,attempts INTEGER,next_check REAL)')
            db.execute('CREATE INDEX IF NOT EXISTS ryze_sent_created ON ryze_sent(created)')

    def sent(self, mid, number):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO ryze_sent VALUES (?,?,'accepted',?,?)", (mid,number,time.time(),time.time()))
            early = self.db.execute('SELECT state,stamp FROM ryze_early_receipts WHERE id=? AND number=? AND expires>?',(mid,number,time.time())).fetchone()
            if early: self._apply(mid,number,*early)
            self.db.execute('DELETE FROM ryze_early_receipts WHERE id=? AND number=?',(mid,number))

    def _apply(self,mid,number,state,stamp):
        row = self.db.execute('SELECT state,created,updated FROM ryze_sent WHERE id=? AND number=?',(mid,number)).fetchone()
        if not row or stamp<row[1]-300: return False
        old = row[0]
        if state in ERRORS and (old in {'delivered','read','played'} or stamp<row[2]): return False
        if state in RANK and RANK[state]<RANK.get(old,0): return False
        self.db.execute('UPDATE ryze_sent SET state=?,updated=max(updated,?) WHERE id=?',(state,stamp,mid))
        return True

    def cleanup(self):
        with self.db:
            self.db.execute('DELETE FROM ryze_early_receipts WHERE expires<=?',(time.time(),))
            self.db.execute('DELETE FROM ryze_sent WHERE created<?',(time.time()-7*86400,))
            self.db.execute('DELETE FROM ryze_receipt_checks WHERE id NOT IN (SELECT id FROM ryze_sent)')

    def reconciliation_candidates(self,recipients):
        now = time.time()
        rows = self.db.execute("SELECT s.id,s.number,coalesce(c.attempts,0) FROM ryze_sent s LEFT JOIN ryze_receipt_checks c ON c.id=s.id WHERE s.state IN ('accepted','delivered','retry','inactive','server_error') AND s.created BETWEEN ? AND ? AND coalesce(c.attempts,0)<5 AND coalesce(c.next_check,0)<=? ORDER BY coalesce(c.next_check,s.created),s.created LIMIT 5",(now-86400,now-30,now)).fetchall()
        result = []
        with self.db:
            for mid,number,attempts in rows:
                if authorized_phone(number,recipients)!=number: continue
                self.db.execute('INSERT INTO ryze_receipt_checks VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET attempts=excluded.attempts,next_check=excluded.next_check',
                                (mid,attempts+1,now+(60,180,600,1800,3600)[attempts]))
                result.append((mid,number))
        return result

    def snapshot(self,value,mid,number,recipients):
        if not isinstance(value,dict) or value.get('message_id')!=mid or value.get('direction')!='sent': return False
        if authorized_phone(value.get('chat_jid'),recipients)!=number: return False
        state = {'pending':'accepted','sent':'accepted','error':'server_error'}.get(value.get('status'),value.get('status'))
        if state not in set(RANK)|ERRORS: return False
        with self.db: return self._apply(mid,number,state,time.time())

    def state(self, state, stamp=None):
        if not isinstance(state,str) or state not in STATES: return False
        stamp = time.time() if stamp is None else stamp
        with self.db:
            self.db.execute('INSERT INTO ryze_state VALUES (1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET state=excluded.state,observed=excluded.observed,stamp=excluded.stamp WHERE excluded.stamp>=ryze_state.stamp', (state,time.time(),stamp))
        return True

    def event(self, payload, instance, recipients):
        if not isinstance(payload,dict) or not isinstance(payload.get('instanceData'),dict) or payload['instanceData'].get('instance')!=instance: return False
        data = payload.get('data')
        if not isinstance(data, dict): return False
        try:
            dt = datetime.fromisoformat(str(data['timestamp']).replace('Z','+00:00'))
            if dt.tzinfo is None: return False
            stamp = dt.timestamp()
            if not -300 <= time.time()-stamp <= 86400: return False
        except (KeyError,TypeError,ValueError): return False
        if payload.get('event') == 'instance.state':
            if data.get('instance', instance) != instance: return False
            return self.state(data.get('state'), stamp)
        if payload.get('event') != 'message.status': return False
        chat = data.get('chat')
        if not isinstance(chat, dict) or chat.get('type') != 'private' or chat.get('isCommunity'): return False
        number = authorized_phone(data.get('recipient') or chat.get('jid'), recipients)
        if not number or authorized_phone(chat.get('jid'), recipients) != number: return False
        state, ids = data.get('status'), data.get('messageIds')
        if not isinstance(state,str) or state not in set(RANK)|ERRORS or not isinstance(ids,list) or len(ids)>256: return False
        updated = False
        with self.db:
            self.db.execute('DELETE FROM ryze_early_receipts WHERE expires<=?',(time.time(),))
            for mid in ids:
                if not isinstance(mid,str) or not 1<=len(mid)<=256: continue
                known = self.db.execute('SELECT 1 FROM ryze_sent WHERE id=?',(mid,)).fetchone()
                if known:
                    updated = self._apply(mid,number,state,stamp) or updated
                    continue
                # Unknown IDs are quarantined, never counted as sends or exposed to the agent.
                early = self.db.execute('SELECT state,stamp FROM ryze_early_receipts WHERE id=? AND number=?',(mid,number)).fetchone()
                if early and (RANK.get(state,-1)<RANK.get(early[0],-1) or stamp<early[1]): continue
                if not early and self.db.execute('SELECT count(*) FROM ryze_early_receipts').fetchone()[0]>=1000: continue
                self.db.execute('INSERT INTO ryze_early_receipts VALUES (?,?,?,?,?) ON CONFLICT(id,number) DO UPDATE SET state=excluded.state,stamp=excluded.stamp',
                                (mid,number,state,stamp,time.time()+300))
        return updated

    def summary(self):
        state = self.db.execute('SELECT state,observed FROM ryze_state WHERE singleton=1').fetchone()
        fresh = bool(state and time.time()-state[1] <= 180)
        rows = self.db.execute("SELECT id,status,created FROM inbox WHERE status IN ('uncertain','expired') ORDER BY created DESC LIMIT 10")
        return {'whatsapp_state':state[0] if state and fresh else 'unknown',
                'early_receipts_pending':self.db.execute('SELECT count(*) FROM ryze_early_receipts WHERE expires>?',(time.time(),)).fetchone()[0],
                'whatsapp_observed_at':state[1] if state else None,
                'delivery_counts':dict(self.db.execute('SELECT state,count(*) FROM ryze_sent WHERE created>? GROUP BY state', (time.time()-7*86400,))),
                'review_items':[{'reference':hashlib.sha256(mid.encode()).hexdigest()[:12],'status':status,'created':created} for mid,status,created in rows]}
