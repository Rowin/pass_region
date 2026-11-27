import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any, cast

import unfold.admin
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
    Session,
    StaffUser,
)

if TYPE_CHECKING:
    _PassRegionInline = admin.TabularInline[PassRegionPayment, PaymentCase]
    _StaffUserInline = admin.StackedInline[StaffUser, User]
    _CardPaymentInline = admin.StackedInline[CardPayment, PaymentCase]

    _PaymentCaseAdmin = unfold.admin.ModelAdmin[PaymentCase]
    _CardPaymentAdmin = unfold.admin.ModelAdmin[CardPayment]
    _APICredentialRecordAdmin = unfold.admin.ModelAdmin[APICredentialRecord]
    _OrganizationAdmin = unfold.admin.ModelAdmin[Organization]
    _SessionAdmin = unfold.admin.ModelAdmin[Session]

else:
    _PassRegionInline = admin.TabularInline
    _StaffUserInline = admin.StackedInline
    _CardPaymentInline = admin.StackedInline

    _PaymentCaseAdmin = unfold.admin.ModelAdmin
    _CardPaymentAdmin = unfold.admin.ModelAdmin
    _APICredentialRecordAdmin = unfold.admin.ModelAdmin
    _OrganizationAdmin = unfold.admin.ModelAdmin
    _SessionAdmin = unfold.admin.ModelAdmin


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

    def has_change_permission(
        self, request: HttpRequest, obj: PaymentCase | None = None
    ) -> bool:
        return True

    def has_delete_permission(
        self, request: HttpRequest, obj: PaymentCase | None = None
    ) -> bool:
        return True


class CardPaymentInline(_CardPaymentInline):
    model = CardPayment
    fields = [
        "payment_created_at",
        "checkout_intent_id",
        "payment_status",
        "payment_confirmation_received_at",
    ]
    readonly_fields = [
        "checkout_intent_id",
        "payment_status",
        "payment_confirmation_received_at",
    ]
    max_num = 0

    def has_view_permission(
        self, request: HttpRequest, obj: PaymentCase | None = None
    ) -> bool:
        return True


@admin.register(PaymentCase)
class PaymentCaseAdmin(_PaymentCaseAdmin):
    form = PaymentCaseAdminForm
    inlines = [PassRegionInline, CardPaymentInline]
    search_fields = [
        "session_number",
        "user__first_name",
        "user__last_name",
        "user__email",
    ]
    list_display = [
        "completed",
        "session_number",
        "user__first_name",
        "user__last_name",
        "user__email",
        "pass_region_count",
    ]
    list_filter = ["session_number", "completed"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[PaymentCase, PaymentCase]:
        user_orgs = get_user_orgs(cast(User, request.user))
        return PaymentCase.objects.filter(organization__in=user_orgs)

    def has_module_permission(self, request: HttpRequest) -> bool:
        return True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return True

    def has_change_permission(
        self, request: HttpRequest, obj: Any | None = None
    ) -> bool:
        return True

    def has_delete_permission(
        self, request: HttpRequest, obj: Any | None = None
    ) -> bool:
        return True

    @staticmethod
    @admin.display(description=_("Pass Région acceptés / attendus"))
    def pass_region_count(obj: PaymentCase) -> str:
        confirmed_payments_count = obj.passregionpayment_set.filter(
            payment_status=PassRegionPayment.PassRegionPaymentChoice.PAYMENT_APPROVED
        ).count()
        return f"{confirmed_payments_count} / {obj.total_payments_required}"

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

        else:
            obj.user.first_name = form.cleaned_data["first_name"]
            obj.user.last_name = form.cleaned_data["last_name"]
            obj.user.email = form.cleaned_data["email"]
            obj.user.save()

            if "email" in cast(PaymentCaseAdminForm, form).changed_data:
                transaction.on_commit(lambda: self.send_magic_link(obj, request))

        super().save_model(request, obj, form, change)

    def send_magic_link(self, payment_case: PaymentCase, request: HttpRequest):
        link = reverse("login")
        link = request.build_absolute_uri(link)
        link += get_query_string(user=payment_case.user)

        notifications.send_payment_creation_notification(payment_case, link)


@admin.register(CardPayment)
class CardPaymentAdmin(_CardPaymentAdmin):
    fields = [
        "payment_case",
        "checkout_intent_id",
        "redirect_url_expires_at",
        "redirect_url",
        "payment_status",
        "payment_confirmation_received_at",
    ]
    list_display = [
        "payment_case__session_number",
        "payment_case__user__first_name",
        "payment_case__user__last_name",
        "payment_status",
    ]
    list_filter = ["payment_case__session_number", "payment_status"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[CardPayment, CardPayment]:
        user_orgs = get_user_orgs(cast(User, request.user))
        return CardPayment.objects.filter(payment_case__organization__in=user_orgs)

    def has_module_permission(self, request: HttpRequest) -> bool:
        return True

    def has_view_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return True


@admin.register(APICredentialRecord)
class APICredentialRecordAdmin(_APICredentialRecordAdmin):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Any | None = ...
    ) -> bool:
        return False


@admin.register(Organization)
class OrganizationAdmin(_OrganizationAdmin):
    form = OrganizationAdminForm
    readonly_fields = ["webhook_url"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Organization]:
        return Organization.objects.filter(
            pk__in=get_user_orgs(cast(User, request.user))
        )

    def has_module_permission(self, request: HttpRequest) -> bool:
        return True

    def has_change_permission(
        self, request: HttpRequest, obj: Any | None = ...
    ) -> bool:
        return True

    @admin.display(description=_("URL du webhook"))
    def webhook_url(self, obj: Organization):
        return urllib.parse.urljoin(
            settings.BASE_URL,
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


class StaffUserInline(_StaffUserInline):
    model = StaffUser


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin, unfold.admin.ModelAdmin):
    inlines = [StaffUserInline]


@admin.register(Session)
class SessionAdmin(_SessionAdmin):
    list_display = ["session_number", "date", "location"]
