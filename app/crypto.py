"""Hybrid packet encryption: RSA-OAEP wraps a per-packet AES-256-GCM key."""
import base64, hashlib, json, os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_DIR = Path("instance")
PRIVATE_KEY_PATH = KEY_DIR / "server_private.pem"
PUBLIC_KEY_PATH = KEY_DIR / "server_public.pem"

class HybridCrypto:
    def __init__(self):
        KEY_DIR.mkdir(exist_ok=True)
        if PRIVATE_KEY_PATH.exists():
            self.private_key = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
        else:
            self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            PRIVATE_KEY_PATH.write_bytes(self.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            try: PRIVATE_KEY_PATH.chmod(0o600)
            except OSError: pass
        PUBLIC_KEY_PATH.write_bytes(self.private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    def encrypt(self, instruction: dict) -> str:
        key = AESGCM.generate_key(bit_length=256); nonce = os.urandom(12)
        encrypted = AESGCM(key).encrypt(nonce, json.dumps(instruction,separators=(",",":")).encode(), None)
        wrapped = self.private_key.public_key().encrypt(key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return base64.b64encode(wrapped + nonce + encrypted).decode()
    def decrypt(self, encoded: str) -> dict:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) < 256 + 12 + 16: raise ValueError("ciphertext_too_short")
        key = self.private_key.decrypt(raw[:256], padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return json.loads(AESGCM(key).decrypt(raw[256:268], raw[268:], None))
    @staticmethod
    def hash_ciphertext(ciphertext: str) -> str:
        return hashlib.sha256(ciphertext.encode()).hexdigest()
