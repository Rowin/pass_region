import uuid
from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db import transaction
from django.forms import CharField, EmailField, ModelForm
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _
from sesame.utils import get_query_string

from main.models import APICredentialRecord, CardPayment, PassRegionPayment, PaymentCase

if TYPE_CHECKING:
    _PassRegionInline = admin.TabularInline[PassRegionPayment, PaymentCase]
    _PaymentCaseAdmin = admin.ModelAdmin[PaymentCase]
    _CardPaymentAdmin = admin.ModelAdmin[CardPayment]
    _APICredentialRecordAdmin = admin.ModelAdmin[APICredentialRecord]

    _PaymentCaseAdminForm = ModelForm[PaymentCase]
else:
    _PassRegionInline = admin.TabularInline
    _PaymentCaseAdmin = admin.ModelAdmin
    _CardPaymentAdmin = admin.ModelAdmin
    _APICredentialRecordAdmin = admin.ModelAdmin

    _PaymentCaseAdminForm = ModelForm


class PassRegionInline(_PassRegionInline):
    model = PassRegionPayment
    fields = [
        "holder_firstname",
        "holder_lastname",
        "card_number",
        "card_pin",
        "payment_status",
        "payment_date",
    ]
    readonly_fields = [
        "holder_firstname",
        "holder_lastname",
        "card_number",
        "card_pin",
        "payment_date",
    ]
    max_num = 0


@admin.register(PaymentCase)
class PaymentCaseAdmin(_PaymentCaseAdmin):
    inlines = [PassRegionInline]
    list_display = [
        "completed",
        "session_number",
        "user__first_name",
        "user__last_name",
        "user__email",
        "pass_region_count",
    ]

    @staticmethod
    @admin.display(description=_("Nombre de paiements pass région"))
    def pass_region_count(obj: PaymentCase) -> str:
        return f"{obj.passregionpayment_set.count()} / {obj.total_payments_required}"

    def save_model(
        self, request: HttpRequest, obj: Any, form: Any, change: Any
    ) -> None:
        if not change:
            obj.user = get_user_model().objects.create_user(
                username=uuid.uuid4().hex,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=form.cleaned_data["email"],
                password=None,
                is_staff=False,
                is_superuser=False,
            )

        transaction.on_commit(lambda: self.send_magic_link(obj.user, request))

        super().save_model(request, obj, form, change)

    def send_magic_link(self, user: User, request: HttpRequest):
        link = reverse("login")
        link = request.build_absolute_uri(link)
        link += get_query_string(user=user)

        print(link)

        user.email_user(
            subject="sesame",
            message=f"Hello {user.first_name} {user.last_name}, Here is your link: {link}",
        )

    class PaymentCaseAdminForm(_PaymentCaseAdminForm):
        first_name = CharField(label=_("Prénom"))
        last_name = CharField(label=_("Nom"))
        email = EmailField(label=_("Mail"))

        class Meta:
            model = PaymentCase
            fields = [
                "completed",
                "first_name",
                "last_name",
                "email",
                "session_number",
                "total_payments_required",
            ]

        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)

            if self.instance.pk:
                self.fields["first_name"].initial = self.instance.user.first_name
                self.fields["last_name"].initial = self.instance.user.last_name
                self.fields["email"].initial = self.instance.user.email

    form = PaymentCaseAdminForm


@admin.register(CardPayment)
class CardPaymentAdmin(_CardPaymentAdmin):
    ...


@admin.register(APICredentialRecord)
class APICredentialRecordAdmin(_APICredentialRecordAdmin):
    ...
