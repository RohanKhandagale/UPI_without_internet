from __future__ import annotations
import hashlib, time, uuid, logging
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from app.config import settings
from app.crypto import HybridCrypto
from app.mesh import MeshSimulator
from app.models import MeshPacket, PaymentRequest
from app.store import init_db, list_accounts, list_transactions, claim_hash, settle, connect

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("upi_mesh")
app=FastAPI(title=settings.app_name,version="1.0.0",description="Educational offline payment mesh simulation")
crypto=HybridCrypto(); mesh=MeshSimulator()
@app.on_event("startup")
def startup(): init_db()
@app.get("/",response_class=HTMLResponse)
def dashboard(): return (Path(__file__).parent/"templates"/"dashboard.html").read_text(encoding="utf-8")
@app.get("/api/health")
def health(): return {"status":"ok","mode":"educational_simulation"}
@app.get("/api/public-key")
def public_key(): return {"algorithm":"RSA-OAEP-SHA256 + AES-256-GCM","public_key_pem":Path("instance/server_public.pem").read_text()}
@app.post("/api/payment")
def create_payment(req:PaymentRequest):
    if req.sender_vpa==req.receiver_vpa: raise HTTPException(400,"Sender and receiver must differ")
    instruction={"sender_vpa":req.sender_vpa,"receiver_vpa":req.receiver_vpa,"amount":round(req.amount,2),"pin_hash":hashlib.sha256(req.pin.encode()).hexdigest(),"nonce":str(uuid.uuid4()),"signed_at":int(time.time()*1000)}
    packet=MeshPacket(packet_id=str(uuid.uuid4()),ttl=req.ttl,created_at=int(time.time()*1000),ciphertext=crypto.encrypt(instruction))
    try: mesh.inject(req.sender_device_id,packet)
    except ValueError as e: raise HTTPException(400,str(e))
    log.info("Packet injected: %s",packet.packet_id[:8]); return packet.model_dump()
@app.post("/api/mesh/gossip")
def gossip(): return mesh.gossip_once()
@app.get("/api/mesh/devices")
def devices():
    return [{"device_id":d.device_id,"has_internet":d.has_internet,"packet_count":d.packet_count(),"packets":[{"packet_id":p.packet_id,"ttl":p.ttl} for p in d.packets.values()]} for d in mesh.devices.values()]
def ingest(packet:MeshPacket,bridge_node_id:str,hop_count:int):
    packet_hash=crypto.hash_ciphertext(packet.ciphertext)
    if not claim_hash(packet_hash): return {"outcome":"DUPLICATE_DROPPED","packet_hash":packet_hash,"reason":None,"transaction_id":None}
    try: instruction=crypto.decrypt(packet.ciphertext)
    except Exception: return {"outcome":"INVALID","packet_hash":packet_hash,"reason":"decryption_failed","transaction_id":None}
    age=(int(time.time()*1000)-int(instruction.get("signed_at",0)))/1000
    if age>settings.packet_max_age_seconds: return {"outcome":"INVALID","packet_hash":packet_hash,"reason":"stale_packet","transaction_id":None}
    if age < -300: return {"outcome":"INVALID","packet_hash":packet_hash,"reason":"future_dated","transaction_id":None}
    return {**settle(instruction,packet_hash,bridge_node_id,hop_count),"packet_hash":packet_hash}
@app.post("/api/bridge/ingest")
def bridge_ingest(packet:MeshPacket,x_bridge_node_id:str=Header(default="unknown"),x_hop_count:int=Header(default=0,ge=0)):
    return ingest(packet,x_bridge_node_id,x_hop_count)
@app.post("/api/mesh/flush")
def flush_bridges():
    uploads=mesh.bridge_uploads(); results=[{"bridge_node_id":node,"packet_id":packet.packet_id,**ingest(packet,node,0)} for node,packet in uploads]
    return {"uploads_attempted":len(uploads),"results":results}
@app.post("/api/mesh/reset")
def reset_mesh():
    mesh.reset()
    with connect() as c: c.execute("DELETE FROM idempotency")
    return {"status":"mesh and idempotency cache cleared"}
@app.get("/api/accounts")
def accounts(): return list_accounts()
@app.get("/api/transactions")
def transactions(): return list_transactions()
