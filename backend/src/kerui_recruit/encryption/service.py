from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet


class EncryptionService:
    """Fernet-based field-level encryption (AES-128-CBC with HMAC).

    Generates a persistent key stored on disk. Suitable for protecting
    sensitive BD lead contact information at rest.
    """

    def __init__(self, key_path: str) -> None:
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_generate_key())

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return base64.urlsafe_b64encode(token).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        token = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        return self._fernet.decrypt(token).decode("utf-8")

    def _load_or_generate_key(self) -> bytes:
        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                return f.read()
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(self._key_path), exist_ok=True)
        with open(self._key_path, "wb") as f:
            f.write(key)
        return key