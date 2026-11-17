from typing import TYPE_CHECKING, Any

from django.core.validators import RegexValidator
from django.forms import (
    CharField,
    EmailField,
    ModelForm,
    PasswordInput,
    ValidationError,
)
from django.utils.translation import gettext as _

from main.models import Organization, PassRegionPayment, PaymentCase

if TYPE_CHECKING:
    _PassRegionPaymentFormBase = ModelForm[PassRegionPayment]
    _PaymentCaseAdminForm = ModelForm[PaymentCase]
    _OrganizationAdminForm = ModelForm[Organization]
else:
    _PassRegionPaymentFormBase = ModelForm
    _PaymentCaseAdminForm = ModelForm
    _OrganizationAdminForm = ModelForm


class PassRegionPaymentForm(_PassRegionPaymentFormBase):
    card_pin = CharField(
        min_length=4,
        max_length=4,
        validators=[RegexValidator(r"\d{4}")],
        widget=PasswordInput(),
    )

    class Meta:
        model = PassRegionPayment
        fields = ["holder_firstname", "holder_lastname", "card_number", "card_pin"]
        widgets = {"card_pin": PasswordInput()}


class PaymentCaseAdminForm(_PaymentCaseAdminForm):
    first_name = CharField(label=_("Prénom"))
    last_name = CharField(label=_("Nom"))
    email = EmailField(label=_("Mail"))

    class Meta:
        model = PaymentCase
        fields = [
            "organization",
            "first_name",
            "last_name",
            "email",
            "session_number",
            "completed",
            "total_payments_required",
        ]

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email


class OrganizationAdminForm(_OrganizationAdminForm):
    new_client_id = CharField(
        label=_("Client ID"),
        required=False,
        strip=False,
        widget=PasswordInput(render_value=False),
        help_text=_("Laisser vide pour conserver les identifiants actuels."),
    )
    new_client_secret = CharField(
        label=_("Client Secret"),
        required=False,
        strip=False,
        widget=PasswordInput(render_value=False),
        help_text=_("Laisser vide pour conserver les identifiants actuels."),
    )

    class Meta:
        model = Organization
        exclude = ["hello_asso_client_id", "hello_asso_client_secret"]
        fields = [
            "organization_name",
            "new_client_id",
            "new_client_secret",
            "hello_asso_organization_slug",
            "copay_amount_per_candidate",
            "copay_message",
        ]
        help_texts = {
            "webhook_url": _(
                "Copiez cette URL dans la configuration du webhook HelloAsso."
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        client_id = cleaned_data.get("new_client_id")
        client_secret = cleaned_data.get("new_client_secret")
        if bool(client_id) != bool(client_secret):
            raise ValidationError(_("Renseigner les deux identifiants ensemble."))
        if self.instance._state.adding and not (client_id and client_secret):
            raise ValidationError(_("Les identifiants sont requis pour la creation."))
        return cleaned_data
