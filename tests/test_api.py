from fastapi.testclient import TestClient
from app.main import app
from app.store import connect, init_db

init_db()
client=TestClient(app)

def setup_function():
    with connect() as c:
        c.execute("DELETE FROM transactions"); c.execute("DELETE FROM idempotency")
        c.execute("UPDATE accounts SET balance_paise=CASE vpa WHEN 'alice@demo' THEN 500000 WHEN 'bob@demo' THEN 100000 WHEN 'carol@demo' THEN 250000 ELSE 50000 END")

def test_health():
    assert client.get("/api/health").json()["status"]=="ok"

def test_packet_is_encrypted_and_duplicate_is_dropped():
    p=client.post("/api/payment",json={"sender_vpa":"alice@demo","receiver_vpa":"bob@demo","amount":100,"pin":"1234"}).json()
    assert "alice@demo" not in p["ciphertext"]
    first=client.post("/api/bridge/ingest",json=p,headers={"X-Bridge-Node-Id":"bridge-a","X-Hop-Count":"2"}).json()
    second=client.post("/api/bridge/ingest",json=p,headers={"X-Bridge-Node-Id":"bridge-b","X-Hop-Count":"3"}).json()
    assert first["outcome"]=="SETTLED"; assert second["outcome"]=="DUPLICATE_DROPPED"
    accounts={a["vpa"]:a["balance"] for a in client.get("/api/accounts").json()}
    assert accounts["alice@demo"]==4900.0; assert accounts["bob@demo"]==1100.0

def test_tampered_packet_is_rejected():
    p=client.post("/api/payment",json={"sender_vpa":"alice@demo","receiver_vpa":"bob@demo","amount":25,"pin":"1234"}).json()
    p["ciphertext"]=p["ciphertext"][:-4]+"AAAA"
    assert client.post("/api/bridge/ingest",json=p).json()["outcome"]=="INVALID"

def test_gossip_moves_packets_to_bridge():
    client.post("/api/payment",json={"sender_vpa":"alice@demo","receiver_vpa":"bob@demo","amount":10,"pin":"1234"})
    assert client.post("/api/mesh/gossip").json()["transfers"]>=1
    assert any(d["device_id"]=="phone-bridge" and d["packet_count"]>=1 for d in client.get("/api/mesh/devices").json())
