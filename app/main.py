"""FastAPI server and REST endpoints for the UPI Offline Mesh demo."""
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from .models import MeshPacket, SendRequest
from .services import MeshApplication

app = FastAPI(title="UPI Offline Mesh — Python Demo", version="1.0.0",
              description="A teaching simulation of encrypted deferred-settlement payments over a virtual gossip mesh.")
mesh_app = MeshApplication()
DASHBOARD = Path(__file__).with_name("templates") / "dashboard.html"
if not DASHBOARD.exists():
    DASHBOARD = Path(__file__).with_name("dashboard.html")

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD.read_text(encoding="utf-8")

@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "project": "upi-offline-mesh-python"}

@app.get("/api/server-key")
def server_key():
    return {"publicKey": mesh_app.crypto.public_key_b64(), "algorithm": "RSA-OAEP-SHA256 + AES-256-GCM"}

@app.get("/api/accounts")
def accounts():
    return [{"vpa": r["vpa"], "holderName": r["holder_name"], "holder": r["holder_name"], "balance": r["balance"]}
            for r in mesh_app.db.rows("SELECT * FROM accounts ORDER BY vpa")]

@app.get("/api/transactions")
def transactions():
    rows = mesh_app.db.rows("SELECT * FROM transactions ORDER BY id DESC LIMIT 20")
    return [{"id": r["id"], "packetHash": r["packet_hash"], "senderVpa": r["sender_vpa"],
             "receiverVpa": r["receiver_vpa"], "sender_vpa": r["sender_vpa"], "receiver_vpa": r["receiver_vpa"],
             "amount": r["amount"], "status": r["status"], "bridgeNodeId": r["bridge_node_id"],
             "bridge_node_id": r["bridge_node_id"], "hopCount": r["hop_count"], "hop_count": r["hop_count"],
             "settledAt": r["settled_at"], "reason": r["reason"]} for r in rows]

@app.get("/api/mesh/state")
def mesh_state():
    cache_size = len(mesh_app.db.rows("SELECT packet_hash FROM idempotency_claims"))
    return mesh_app.mesh.state(cache_size)

@app.get("/api/mesh/devices")
def mesh_devices():
    state = mesh_app.mesh.state(len(mesh_app.db.rows("SELECT packet_hash FROM idempotency_claims")))
    result = []
    for device in state["devices"]:
        packets = mesh_app.mesh.devices[device["deviceId"]].packets.values()
        result.append({"device_id": device["deviceId"], "has_internet": device["hasInternet"],
                       "packet_count": device["packetCount"],
                       "packets": [{"packet_id": p.packetId, "ttl": p.ttl} for p in packets]})
    return result

@app.post("/api/demo/send")
def demo_send(request: SendRequest):
    try:
        return mesh_app.create_packet(request.senderVpa, request.receiverVpa, request.amount,
                                      request.pin, request.ttl, request.startDevice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/payment")
def create_payment_compat(payload: dict):
    """Snake-case alias retained for the repository's original Python dashboard/API."""
    try:
        result = mesh_app.create_packet(payload.get("sender_vpa", ""), payload.get("receiver_vpa", ""),
                                        float(payload.get("amount", 0)), str(payload.get("pin", "")),
                                        int(payload.get("ttl", 5)), payload.get("sender_device_id", "phone-alice"))
        return {"packet_id": result["packetId"], "packetId": result["packetId"], "ttl": result["ttl"],
                "created_at": result["injectedAt"], "createdAt": result["injectedAt"],
                "ciphertext": result["ciphertext"], "ciphertext_preview": result["ciphertextPreview"]}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/mesh/gossip")
def gossip():
    return mesh_app.mesh.gossip_round()

@app.post("/api/mesh/flush")
def flush():
    return mesh_app.flush_bridges()

@app.post("/api/mesh/reset")
def reset():
    mesh_app.mesh.reset()
    mesh_app.db.clear_ledger_and_claims()
    return {"status": "reset"}

@app.post("/api/bridge/ingest")
def bridge_ingest(packet: MeshPacket, x_bridge_node_id: str = Header(default="unknown-bridge"),
                  x_hop_count: int = Header(default=0)):
    # Demo endpoint only. Production deployments must authenticate bridge identities (e.g. mTLS).
    return mesh_app.ingest(packet, x_bridge_node_id, max(0, x_hop_count))
