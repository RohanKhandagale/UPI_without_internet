"""RSA-OAEP + AES-256-GCM hybrid encryption used by the demo."""
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RSA_KEY_BYTES = 256
IV_BYTES = 12


class HybridCrypto:
    def __init__(self, key_path: str | Path | None = None):
        # A stable key is needed when an offline phone caches the public key.
        # Override the path for deployment; production should use a managed KMS/HSM.
        configured_path = key_path or os.getenv("UPI_NETWORK_PRIVATE_KEY_PATH", "data/server_private_key.pem")
        self._key_path = Path(configured_path)
        self._private_key = self._load_or_create_private_key(self._key_path)
        self._public_key = self._private_key.public_key()

    @staticmethod
    def _load_or_create_private_key(path: Path):
        if path.exists():
            return serialization.load_pem_private_key(path.read_bytes(), password=None)

        path.parent.mkdir(parents=True, exist_ok=True)
        candidate = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = candidate.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        try:
            # Exclusive create prevents two starting processes from overwriting each other's key.
            with path.open("xb") as key_file:
                key_file.write(pem)
            if os.name != "nt":
                path.chmod(0o600)
            return candidate
        except FileExistsError:
            return serialization.load_pem_private_key(path.read_bytes(), password=None)

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
