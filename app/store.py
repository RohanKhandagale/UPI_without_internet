"""SQLite persistence; monetary values are stored as integer paise."""
import sqlite3, threading, time
from app.config import settings
LOCK=threading.RLock()
ACCOUNTS=[("alice@demo","Alice",500000),("bob@demo","Bob",100000),("carol@demo","Carol",250000),("dave@demo","Dave",50000)]
def connect():
    c=sqlite3.connect(settings.database_path,timeout=15,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c
def init_db():
    with connect() as c:
        c.executescript("""CREATE TABLE IF NOT EXISTS accounts(vpa TEXT PRIMARY KEY,holder TEXT NOT NULL,balance_paise INTEGER NOT NULL CHECK(balance_paise>=0)); CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,packet_hash TEXT NOT NULL UNIQUE,sender_vpa TEXT NOT NULL,receiver_vpa TEXT NOT NULL,amount_paise INTEGER NOT NULL,signed_at INTEGER NOT NULL,settled_at INTEGER NOT NULL,bridge_node_id TEXT NOT NULL,hop_count INTEGER NOT NULL,status TEXT NOT NULL,reason TEXT); CREATE TABLE IF NOT EXISTS idempotency(packet_hash TEXT PRIMARY KEY,claimed_at INTEGER NOT NULL);""")
        for row in ACCOUNTS: c.execute("INSERT OR IGNORE INTO accounts(vpa,holder,balance_paise) VALUES(?,?,?)",row)
def list_accounts():
    with connect() as c: return [dict(r,balance=round(r["balance_paise"]/100,2)) for r in c.execute("SELECT * FROM accounts ORDER BY vpa")]
def list_transactions():
    with connect() as c: return [dict(r,amount=round(r["amount_paise"]/100,2)) for r in c.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 20")]
def claim_hash(packet_hash):
    now=int(time.time())
    with LOCK,connect() as c:
        c.execute("DELETE FROM idempotency WHERE claimed_at < ?",(now-settings.idempotency_ttl_seconds,))
        try: c.execute("INSERT INTO idempotency(packet_hash,claimed_at) VALUES(?,?)",(packet_hash,now)); return True
        except sqlite3.IntegrityError: return False
def settle(instruction,packet_hash,bridge,hops):
    amount=round(float(instruction["amount"])*100)
    with LOCK,connect() as c:
        c.execute("BEGIN IMMEDIATE"); sender=c.execute("SELECT * FROM accounts WHERE vpa=?",(instruction["sender_vpa"],)).fetchone(); receiver=c.execute("SELECT * FROM accounts WHERE vpa=?",(instruction["receiver_vpa"],)).fetchone()
        status="SETTLED"; reason=None
        if not sender or not receiver: status,reason="REJECTED","unknown_vpa"
        elif amount<=0: status,reason="REJECTED","invalid_amount"
        elif sender["balance_paise"]<amount: status,reason="REJECTED","insufficient_balance"
        if status=="SETTLED":
            c.execute("UPDATE accounts SET balance_paise=balance_paise-? WHERE vpa=?",(amount,sender["vpa"])); c.execute("UPDATE accounts SET balance_paise=balance_paise+? WHERE vpa=?",(amount,receiver["vpa"]))
        cur=c.execute("INSERT INTO transactions(packet_hash,sender_vpa,receiver_vpa,amount_paise,signed_at,settled_at,bridge_node_id,hop_count,status,reason) VALUES(?,?,?,?,?,?,?,?,?,?)",(packet_hash,instruction["sender_vpa"],instruction["receiver_vpa"],amount,int(instruction["signed_at"]),int(time.time()*1000),bridge,hops,status,reason))
        return {"transaction_id":cur.lastrowid,"outcome":status,"reason":reason}
