import ssl
from base64 import urlsafe_b64encode
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from requests.adapters import HTTPAdapter
from requests.models import PreparedRequest


class _RelaxedX509HTTPAdapter(HTTPAdapter):
    """Keep TLS verification while relaxing strict X.509 chain checks."""

    def __init__(self) -> None:
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        super().__init__()

    def build_connection_pool_key_attributes(
        self,
        request: PreparedRequest,
        verify: bool | str,
        cert: str | tuple[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert
        )
        pool_kwargs["ssl_context"] = self._ssl_context
        return host_params, pool_kwargs


def fernet_from_seed(seed: str) -> Fernet:
    key_bytes = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"pass-region/fernet/v1"
    ).derive(seed.encode("utf-8"))

    return Fernet(urlsafe_b64encode(key_bytes))
