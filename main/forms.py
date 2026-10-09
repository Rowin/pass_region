from typing import TYPE_CHECKING

from django.forms import ModelForm, PasswordInput, CharField
from django.core.validators import RegexValidator

from main.models import PassRegionPayment


if TYPE_CHECKING:
    _PassRegionPaymentFormBase = ModelForm[PassRegionPayment]
else:
    _PassRegionPaymentFormBase = ModelForm

class PassRegionPaymentForm(_PassRegionPaymentFormBase):
    card_pin = CharField(min_length=4, max_length=4, validators=[RegexValidator(r"\d{4}")], widget=PasswordInput())

    class Meta:
        model = PassRegionPayment
        fields = ['holder_firstname', 'holder_lastname', 'card_number', 'card_pin']
        widgets = {
            "card_pin": PasswordInput()
        }
