import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _
from sesame.utils import get_query_string

from main import notifications
from main.forms import OrganizationAdminForm, PaymentCaseAdminForm
from main.models import (
    APICredentialRecord,
    CardPayment,
    Organization,
    PassRegionPayment,
    PaymentCase,
    StaffUser,
)

if TYPE_CHECKING:
    _PassRegionInline = admin.TabularInline[PassRegionPayment, PaymentCase]
    _StaffUserInline = admin.StackedInline[StaffUser, User]

    _PaymentCaseAdmin = admin.ModelAdmin[PaymentCase]
    _CardPaymentAdmin = admin.ModelAdmin[CardPayment]
    _APICredentialRecordAdmin = admin.ModelAdmin[APICredentialRecord]
    _OrganizationAdmin = admin.ModelAdmin[Organization]

else:
    _PassRegionInline = admin.TabularInline
    _StaffUserInline = admin.StackedInline

    _PaymentCaseAdmin = admin.ModelAdmin
    _CardPaymentAdmin = admin.ModelAdmin
    _APICredentialRecordAdmin = admin.ModelAdmin
    _OrganizationAdmin = admin.ModelAdmin


def get_user_orgs(user: User) -> QuerySet[Organization]:
    if user.is_superuser:
        return Organization.objects.all()
    elif hasattr(user, "staffuser"):
        user_orgs: QuerySet[Organization] = Organization.objects.filter(
            staffuser__user=user
        )
        return user_orgs
    else:
        return Organization.objects.none()


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
    form = PaymentCaseAdminForm
    inlines = [PassRegionInline]
    list_display = [
        "completed",
        "session_number",
        "user__first_name",
        "user__last_name",
        "user__email",
        "pass_region_count",
    ]

    def get_queryset(self, request: HttpRequest) -> QuerySet[PaymentCase, PaymentCase]:
        user_orgs = get_user_orgs(cast(User, request.user))
        return PaymentCase.objects.filter(organization__in=user_orgs)

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

        transaction.on_commit(lambda: self.send_magic_link(obj, request))

        super().save_model(request, obj, form, change)

    def send_magic_link(self, payment_case: PaymentCase, request: HttpRequest):
        link = reverse("login")
        link = request.build_absolute_uri(link)
        link += get_query_string(user=payment_case.user)

        notifications.send_payment_creation_notification(payment_case, link)


@admin.register(CardPayment)
class CardPaymentAdmin(_CardPaymentAdmin):
    fields = ["payment_status", "payment_confirmation_received_at"]
    list_display = [
        "payment_case__session_number",
        "payment_case__user__first_name",
        "payment_case__user__last_name",
        "payment_status",
    ]
    list_filter = ["payment_case__session_number", "payment_status"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def get_queryset(self, request: HttpRequest) -> QuerySet[CardPayment, CardPayment]:
        user_orgs = get_user_orgs(cast(User, request.user))
        return CardPayment.objects.filter(payment_case__organization__in=user_orgs)


@admin.register(APICredentialRecord)
class APICredentialRecordAdmin(_APICredentialRecordAdmin):
    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(Organization)
class OrganizationAdmin(_OrganizationAdmin):
    form = OrganizationAdminForm
    readonly_fields = ["webhook_url"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Organization]:
        return (
            super()
            .get_queryset(request)
            .filter(pk__in=get_user_orgs(cast(User, request.user)))
        )

    @admin.display(description=_("URL du webhook"))
    def webhook_url(self, obj: Organization):
        return urllib.parse.urljoin(
            settings.HELLO_ASSO_CALLBACK_BASE_URL,
            reverse("webhook", args=[obj.webhook_uuid]),
        )

    def save_model(
        self, request: HttpRequest, obj: Organization, form: Any, change: bool
    ) -> None:
        if form.cleaned_data.get("new_client_id"):
            obj.hello_asso_client_id = form.cleaned_data["new_client_id"]
            obj.hello_asso_client_secret = form.cleaned_data["new_client_secret"]
            super().save_model(request, obj, form, change)
            APICredentialRecord.objects.filter(organization=obj).delete()
        else:
            super().save_model(request, obj, form, change)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser


class StaffUserInline(_StaffUserInline):
    model = StaffUser


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [StaffUserInline]
