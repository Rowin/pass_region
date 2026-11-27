import json
import logging
import uuid
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.db.models.base import Model as ModelBase
from django.forms import formset_factory
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import decorators, timezone
from django.utils.translation import gettext as _
from django.views.decorators import csrf
from django.views.generic import CreateView, DetailView, RedirectView, View
from probatio import Invalid

import main.hello_asso
import main.schemas
from main import notifications
from main.forms import PassRegionPaymentForm
from main.models import (
    CardPayment,
    Organization,
    PassRegionPayment,
    PaymentCase,
    Session,
)

logger = logging.getLogger(__name__)


class PaymentCaseDetail(DetailView):
    model = PaymentCase
    context_object_name = "payment_case"
    http_method_names = ["get", "post"]

    def get_object(self, queryset: QuerySet[Any, Any] | None = None) -> ModelBase:
        if self.request.user.is_authenticated:
            return get_object_or_404(PaymentCase, user=self.request.user)
        else:
            raise PermissionDenied

    def get_formset(self):
        payment_case: PaymentCase = cast(PaymentCase, self.get_object())

        missing_pass_region: int = (
            payment_case.total_payments_required
            - payment_case.passregionpayment_set.exclude(
                payment_status=PassRegionPayment.PassRegionPaymentChoice.PAYMENT_REJECTED
            ).count()
        )
        PassRegionPaymentFormset = formset_factory(
            PassRegionPaymentForm,
            extra=missing_pass_region,
            max_num=missing_pass_region,
        )

        return PassRegionPaymentFormset(
            data=self.request.POST if self.request.method == "POST" else None
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        object: PaymentCase = cast(PaymentCase, self.object)

        if "formset" not in context:
            context["formset"] = self.get_formset()

        is_payment_form: bool = not object.cardpayment_set.filter(
            Q(payment_status=CardPayment.CardPaymentChoice.PAYMENT_CONFIRMED)
            | Q(payment_status=CardPayment.CardPaymentChoice.WAITING_CONFIRMATION)
        ).exists()
        context["is_payment_form"] = is_payment_form

        card_payments: QuerySet[CardPayment] = object.cardpayment_set.exclude(
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT
        )
        context["card_payments"] = card_payments

        session: Session = Session.objects.get_or_fetch(object.session_number)
        context["session"] = session

        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.object = self.get_object()
        payment_case: PaymentCase = cast(PaymentCase, self.object)
        formset = self.get_formset()

        if not formset.is_valid():
            return self.render_to_response(self.get_context_data(formset=formset))

        for form in formset:
            if not form.has_changed():
                continue

            form.instance.payment_case = payment_case
            form.save()

        return HttpResponseRedirect(reverse("payment-case"))


class PassRegionPaymentCreate(LoginRequiredMixin, CreateView):
    model = PassRegionPayment
    form_class = PassRegionPaymentForm

    def get_success_url(self) -> str:
        return reverse("payment-case")

    def form_valid(self, form: PassRegionPaymentForm):
        form.instance.payment_case = PaymentCase.objects.get(user=self.request.user)
        form.instance.payment_status = (
            PassRegionPayment.PassRegionPaymentChoice.WAITING_PAYMENT
        )

        return super().form_valid(form)


class CardPaymenRedirect(LoginRequiredMixin, RedirectView):
    http_method_names = ["post"]

    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        payment_case = PaymentCase.objects.get(user=self.request.user)

        card_payment = (
            CardPayment.objects.filter(
                payment_case=payment_case,
                redirect_url_expires_at__gt=timezone.now(),
                payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT,
            )
            .order_by("-pk")
            .first()
        )

        if card_payment is None:
            hello_asso_api = main.hello_asso.HelloAssoAPI(payment_case.organization)
            checkout_intent_id, redirect_url = hello_asso_api.create_checkout_intent(
                amount=payment_case.total_amount_required(),
                message=payment_case.organization.copay_message,
            )

            card_payment = CardPayment(
                payment_case=payment_case,
                redirect_url=redirect_url,
                checkout_intent_id=checkout_intent_id,
                redirect_url_expires_at=timezone.now()
                + timezone.timedelta(
                    minutes=10
                ),  # HelloAsso API announces 15 minutes before expiration
            )
            card_payment.save()

        return card_payment.redirect_url


class CardPaymentCallback(LoginRequiredMixin, RedirectView):
    """Handle untrusted browser returns without confirming a payment.

    WAITING_PAYMENT can become PAYMENT_SUCCESS pending reconciliation, or
    PAYMENT_FAILED on an error return. Confirmed payments cannot be overwritten.
    """

    http_method_names = ["get"]

    def get(
        self,
        request: HttpRequest,
        callback_type: str,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        """Validate the return, enforce ownership and record provisional success."""
        for parameter in ("checkoutIntentId", "code"):
            if len(request.GET.getlist(parameter)) > 1:
                return HttpResponseBadRequest(_("Paramètres de retour invalides."))

        match callback_type:
            case "back":
                pass
            case "error" | "return":
                checkout_intent_id = request.GET.get("checkoutIntentId")
                if not checkout_intent_id:
                    return HttpResponseBadRequest(
                        _("Identifiant de paiement manquant.")
                    )

                card_payment = get_object_or_404(
                    CardPayment,
                    checkout_intent_id=checkout_intent_id,
                    payment_case__user=request.user,
                )
                # Keep the status condition in the SQL UPDATE, rather than saving
                # a stale instance that could overwrite concurrent reconciliation.
                # A non-waiting payment matches no rows and remains unchanged.
                pending_payments = CardPayment.objects.filter(
                    pk=card_payment.pk,
                    payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT,
                )

                if callback_type == "return" and request.GET.get("code") == "succeeded":
                    updated = pending_payments.update(
                        payment_status=CardPayment.CardPaymentChoice.WAITING_CONFIRMATION
                    )
                    if updated:
                        messages.info(
                            request,
                            _(
                                "Paiement signalé comme réussi, en attente de vérification."
                            ),
                        )
                elif callback_type == "error":
                    updated = pending_payments.update(
                        payment_status=CardPayment.CardPaymentChoice.PAYMENT_FAILED
                    )
                    if updated:
                        messages.error(request, _("Paiement échoué !"))
            case _:
                return HttpResponseBadRequest(_("Type de retour invalide."))

        return HttpResponseRedirect(reverse("payment-case"))


@decorators.method_decorator(csrf.csrf_exempt, "dispatch")
class HelloAssoWebhook(View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest, org_uuid: uuid.UUID):
        organization = get_object_or_404(Organization, webhook_uuid=org_uuid)

        try:
            data = main.schemas.WEBHOOK_REQUEST_SCHEMA(json.loads(request.body))
        except Invalid as err:
            logger.warning(
                f"Receiving unexpected webhook request, schema parsing failed with: {err}"
            )
            return HttpResponse()
        except json.JSONDecodeError as err:
            logger.warning("Failed to decode webhook data: %s", err)
            return HttpResponse()

        if data["data"]["payments"][0]["state"] == "Authorized":
            card_payments = CardPayment.objects.filter(
                checkout_intent_id=data["data"]["checkoutIntentId"],
                payment_case__organization=organization,
            )
            card_payments.update(
                payment_status=CardPayment.CardPaymentChoice.PAYMENT_CONFIRMED,
                payment_confirmation_received_at=timezone.now(),
            )
            card_payment = card_payments.first()

            notifications.send_credit_card_payment_confirmation_notification(
                card_payment.payment_case
            )

        return HttpResponse()
