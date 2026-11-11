from typing import Any, Optional

from django.conf import settings
from django.db import models

from main.utils import fernet_from_seed


class EncryptedCharField(models.CharField):
    def get_prep_value(self, value: Optional[str]):
        value = super().get_prep_value(value)
        if value is None:
            return None
        return (
            fernet_from_seed(settings.CARD_PIN_FERNET_KEYS)
            .encrypt(value.encode("utf-8"))
            .decode("ascii")
        )

    def from_db_value(
        self, value: Optional[str], expression: Optional[Any], connection: Optional[Any]
    ):
        if value is None:
            return None
        return (
            fernet_from_seed(settings.CARD_PIN_FERNET_KEYS)
            .decrypt(value.encode("ascii"))
            .decode("utf-8")
        )
