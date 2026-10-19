from typing import Any
import uuid

from django.contrib import admin
from django.forms import ModelForm, CharField, EmailField
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.db import transaction
from django.utils.translation import gettext as _

from sesame.utils import get_query_string

from main.models import PaymentCase, PassRegionPayment

class PassRegionInline(admin.TabularInline):
    model = PassRegionPayment
    fields = ["holder_firstname", "holder_lastname", "card_number", "card_pin", "payment_status", "payment_date"]
    readonly_fields = ["holder_firstname", "holder_lastname", "card_number", "card_pin", "payment_date"]
    max_num = 0

@admin.register(PaymentCase)
class PaymentCaseAdmin(admin.ModelAdmin):
    inlines = [PassRegionInline]
    list_display = ["session_number", "user__first_name", "user__last_name", "user__email"]

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: Any) -> None:
        if not change:
            obj.user = get_user_model().objects.create_user(
                username=uuid.uuid4().hex,
                first_name = form.cleaned_data["first_name"],
                password=None,
                is_staff=False,
                is_superuser=False
            )

        transaction.on_commit(lambda: print(get_query_string(user=obj.user)))
        
        super().save_model(request, obj, form, change)

    class PaymentCaseAdminForm(ModelForm):
        first_name = CharField(label=_("Prénom"))
        last_name = CharField(label=_("Nom"))
        email = EmailField(label=_("Mail"))

        class Meta:
            model = PaymentCase
            fields = ["first_name", "last_name", "email", "session_number", "required_pass_region"]

    form = PaymentCaseAdminForm

@admin.register(PassRegionPayment)
class PassRegionPaymentAdmin(admin.ModelAdmin):
    ...
