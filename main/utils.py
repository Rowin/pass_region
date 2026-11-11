from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def fernet_from_seed(seed: str) -> Fernet:
    key_bytes = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"pass-region/fernet/v1"
    ).derive(seed.encode("utf-8"))

    return Fernet(urlsafe_b64encode(key_bytes))
