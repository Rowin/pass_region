from django.utils.timezone import datetime, timedelta

from main.models import APICredentialRecord

class HelloAssoAPI:
    @property
    def access_token(self):
        min_token_availability = datetime.now() + timedelta(minutes=2)
        available_token = APICredentialRecord.objects.filter(access_token_expires_at__date__gt=min_token_availability).order_by("-access_token_expires_at").first()

        if available_token is not None:
            return available_token.access_token