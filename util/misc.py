import re
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import config

_key = bytes.fromhex(config.AES_SECRET_KEY)
_gcm = AESGCM(_key)

NONCE_SIZE = 12


def encrypt(data: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = _gcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt(data: bytes) -> bytes:
    nonce = data[:NONCE_SIZE]
    ciphertext = data[NONCE_SIZE:]
    return _gcm.decrypt(nonce, ciphertext, None)

def extract_encrypted_call_data(payload: str) -> dict:
    encrypted: str = base64.b64decode(payload.split(":")[1]).decode(encoding = "latin1")

    return {
        "token": re.search(r'"tkn":"([^"]+)"', encrypted).group(1).replace("=", "%3D")
    }