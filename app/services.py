"""Application services: packet creation, idempotency, settlement and ingestion."""
import hashlib
import os
import time
import uuid
from datetime import datetime, timezone
from .crypto import HybridCrypto
from .database import Database
from .network import NetworkSimulator
from .models import NetworkPacket

MAX_PACKET_AGE_SECONDS = int(os.getenv("UPI_NETWORK_MAX_PACKET_AGE_SECONDS", "86400"))

class NetworkApplication:
    def __init__(self, db: Database | None = None, crypto: HybridCrypto | None = None, network: NetworkSimulator | None = None):
        self.db = db or Database()
        self.crypto = crypto or HybridCrypto()
        self.network = network or NetworkSimulator()

    def create_packet(self, sender: str, receiver: str, amount: float, pin: str, ttl: int, start_device: str):
        if sender == receiver:
            raise ValueError("sender_and_receiver_must_differ")
        known = {r["vpa"] for r in self.db.rows("SELECT vpa FROM accounts")}
        if sender not in known or receiver not in known:
            raise ValueError("unknown_account")
        if amount <= 0:
            raise ValueError("amount_must_be_positive")
        now_ms = int(time.time() * 1000)
        instruction = {"senderVpa": sender, "receiverVpa": receiver, "amount": round(float(amount), 2),
                       "pinHash": hashlib.sha256(pin.encode()).hexdigest(), "nonce": str(uuid.uuid4()), "signedAt": now_ms}
        ciphertext = self.crypto.encrypt(instruction)
        packet = NetworkPacket(packetId=str(uuid.uuid4()), ttl=ttl, createdAt=now_ms, ciphertext=ciphertext)
        self.network.inject(start_device, packet)
        return {"packetId": packet.packetId, "ttl": packet.ttl, "injectedAt": now_ms,
                "ciphertextPreview": ciphertext[:52] + "...", "ciphertext": ciphertext}

    def claim(self, packet_hash: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        # A unique primary-key insert is atomic for threads/processes sharing this SQLite DB.
        # Multi-host production deployments should use a shared atomic claim such as Redis SET NX.
        with self.db.transaction() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO idempotency_claims(packet_hash, claimed_at) VALUES (?, ?)", (packet_hash, now))
            return cursor.rowcount == 1

    def settle(self, instruction: dict, packet_hash: str, bridge_id: str, hops: int):
        sender = str(instruction.get("senderVpa", ""))
        receiver = str(instruction.get("receiverVpa", ""))
        try:
            amount = round(float(instruction.get("amount", 0)), 2)
            signed_at = int(instruction.get("signedAt", 0))
        except (TypeError, ValueError):
            return {"outcome": "INVALID", "packetHash": packet_hash, "reason": "invalid_payload", "transactionId": None}
        if not sender or not receiver or sender == receiver or amount <= 0 or signed_at <= 0:
            return {"outcome": "INVALID", "packetHash": packet_hash, "reason": "invalid_payload", "transactionId": None}
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.db.transaction() as conn:
                accounts = {r["vpa"]: r for r in conn.execute("SELECT * FROM accounts WHERE vpa IN (?, ?)", (sender, receiver)).fetchall()}
                if sender not in accounts or receiver not in accounts:
                    conn.execute("INSERT INTO transactions(packet_hash,sender_vpa,receiver_vpa,amount,status,bridge_node_id,hop_count,settled_at,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                                 (packet_hash, sender, receiver, amount, "REJECTED", bridge_id, hops, now, "account_not_found"))
                    return {"outcome": "REJECTED", "packetHash": packet_hash, "reason": "account_not_found", "transactionId": None}
                if float(accounts[sender]["balance"]) < amount:
                    conn.execute("INSERT INTO transactions(packet_hash,sender_vpa,receiver_vpa,amount,status,bridge_node_id,hop_count,settled_at,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                                 (packet_hash, sender, receiver, amount, "REJECTED", bridge_id, hops, now, "insufficient_funds"))
                    return {"outcome": "REJECTED", "packetHash": packet_hash, "reason": "insufficient_funds", "transactionId": None}
                conn.execute("UPDATE accounts SET balance = balance - ? WHERE vpa = ?", (amount, sender))
                conn.execute("UPDATE accounts SET balance = balance + ? WHERE vpa = ?", (amount, receiver))
                cursor = conn.execute("INSERT INTO transactions(packet_hash,sender_vpa,receiver_vpa,amount,status,bridge_node_id,hop_count,settled_at,reason) VALUES(?,?,?,?,?,?,?,?,NULL)",
                                      (packet_hash, sender, receiver, amount, "SETTLED", bridge_id, hops, now))
                return {"outcome": "SETTLED", "packetHash": packet_hash, "reason": None, "transactionId": cursor.lastrowid}
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return {"outcome": "DUPLICATE_DROPPED", "packetHash": packet_hash, "reason": None, "transactionId": None}
            raise

    def ingest(self, packet: NetworkPacket, bridge_node_id: str, hop_count: int = 0):
        packet_hash = self.crypto.hash_ciphertext(packet.ciphertext)
        if not self.claim(packet_hash):
            return {"outcome": "DUPLICATE_DROPPED", "packetHash": packet_hash, "reason": None, "transactionId": None}
        try:
            instruction = self.crypto.decrypt(packet.ciphertext)
        except ValueError:
            return {"outcome": "INVALID", "packetHash": packet_hash, "reason": "decryption_failed", "transactionId": None}
        try:
            age = (int(time.time() * 1000) - int(instruction.get("signedAt", 0))) / 1000
        except (TypeError, ValueError):
            return {"outcome": "INVALID", "packetHash": packet_hash, "reason": "invalid_signed_at", "transactionId": None}
        if age > MAX_PACKET_AGE_SECONDS:
            return {"outcome": "INVALID", "packetHash": packet_hash, "reason": "stale_packet", "transactionId": None}
        if age < -300:
            return {"outcome": "INVALID", "packetHash": packet_hash, "reason": "future_dated", "transactionId": None}
        return self.settle(instruction, packet_hash, bridge_node_id, hop_count)

    def flush_bridges(self):
        results = []
        attempted = 0
        for bridge_id, packets in self.network.bridge_packets():
            for packet in packets:
                attempted += 1
                result = self.ingest(packet, bridge_id, 0)
                results.append({"bridgeNode": bridge_id, "packetId": packet.packetId, **result})
        return {"uploadsAttempted": attempted, "results": results}
