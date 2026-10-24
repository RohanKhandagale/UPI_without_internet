"""RSA-OAEP + AES-256-GCM hybrid encryption used by the demo."""
import base64
import hashlib
import json
import os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RSA_KEY_BYTES = 256
IV_BYTES = 12

class HybridCrypto:
    def __init__(self):
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public_key = self._private_key.public_key()

    def public_key_b64(self) -> str:
        der = self._public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return base64.b64encode(der).decode("ascii")

    def encrypt(self, instruction: dict) -> str:
        plaintext = json.dumps(instruction, separators=(",", ":"), sort_keys=True).encode("utf-8")
        aes_key = AESGCM.generate_key(bit_length=256)
        iv = os.urandom(IV_BYTES)
        encrypted_payload = AESGCM(aes_key).encrypt(iv, plaintext, None)
        wrapped_key = self._public_key.encrypt(
            aes_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        return base64.b64encode(wrapped_key + iv + encrypted_payload).decode("ascii")

    def decrypt(self, ciphertext_b64: str) -> dict:
        try:
            raw = base64.b64decode(ciphertext_b64, validate=True)
            if len(raw) < RSA_KEY_BYTES + IV_BYTES + 16:
                raise ValueError("ciphertext_too_short")
            wrapped_key = raw[:RSA_KEY_BYTES]
            iv = raw[RSA_KEY_BYTES:RSA_KEY_BYTES + IV_BYTES]
            encrypted_payload = raw[RSA_KEY_BYTES + IV_BYTES:]
            aes_key = self._private_key.decrypt(
                wrapped_key,
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
            )
            plaintext = AESGCM(aes_key).decrypt(iv, encrypted_payload, None)
            value = json.loads(plaintext.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("payload_not_object")
            return value
        except Exception as exc:
            raise ValueError("decryption_failed") from exc

    @staticmethod
    def hash_ciphertext(ciphertext_b64: str) -> str:
        return hashlib.sha256(ciphertext_b64.encode("utf-8")).hexdigest()
