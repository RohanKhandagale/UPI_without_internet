import base64
import time
from concurrent.futures import ThreadPoolExecutor
from app.crypto import HybridCrypto
from app.database import Database
from app.mesh import MeshSimulator
from app.models import MeshPacket
from app.services import MeshApplication

def make_app(tmp_path):
    return MeshApplication(Database(str(tmp_path / "test.db")), HybridCrypto(), MeshSimulator())

def make_packet(app, **overrides):
    instruction = {"senderVpa": "alice@demo", "receiverVpa": "bob@demo", "amount": 100.0,
                   "pinHash": "not-used-in-demo", "nonce": "nonce-test", "signedAt": int(time.time() * 1000)}
    instruction.update(overrides)
    return MeshPacket(packetId="packet-test", ttl=5, createdAt=int(time.time() * 1000), ciphertext=app.crypto.encrypt(instruction))

def test_encrypt_decrypt_round_trip(tmp_path):
    app = make_app(tmp_path)
    payload = {"senderVpa": "alice@demo", "amount": 10, "signedAt": 123, "nonce": "n"}
    assert app.crypto.decrypt(app.crypto.encrypt(payload)) == payload

def test_tampered_ciphertext_is_rejected(tmp_path):
    app = make_app(tmp_path)
    packet = make_packet(app)
    raw = bytearray(base64.b64decode(packet.ciphertext))
    raw[-1] ^= 1
    tampered = packet.model_copy(update={"ciphertext": base64.b64encode(raw).decode()})
    result = app.ingest(tampered, "bridge-test")
    assert result["outcome"] == "INVALID"
    assert result["reason"] == "decryption_failed"

def test_same_packet_delivered_concurrently_settles_once(tmp_path):
    app = make_app(tmp_path)
    packet = make_packet(app)
    before = {a["vpa"]: a["balance"] for a in app.db.rows("SELECT * FROM accounts")}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda i: app.ingest(packet, f"bridge-{i}"), range(3)))
    assert sorted(r["outcome"] for r in results) == ["DUPLICATE_DROPPED", "DUPLICATE_DROPPED", "SETTLED"]
    after = {a["vpa"]: a["balance"] for a in app.db.rows("SELECT * FROM accounts")}
    assert before["alice@demo"] - after["alice@demo"] == 100
    assert after["bob@demo"] - before["bob@demo"] == 100
    assert len(app.db.rows("SELECT * FROM transactions WHERE status='SETTLED'")) == 1

def test_gossip_propagates_packets(tmp_path):
    app = make_app(tmp_path)
    app.create_packet("alice@demo", "bob@demo", 10, "1234", 5, "phone-alice")
    state = app.mesh.gossip_round()
    assert state["transfers"] > 0
    assert all(d["packetCount"] == 1 for d in app.mesh.state(0)["devices"])
