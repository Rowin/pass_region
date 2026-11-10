from typing import Any, cast

from django.forms import formset_factory
from django.db.models import QuerySet
from django.db.models.base import Model as ModelBase
from django.views.generic import DetailView, CreateView, RedirectView
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.contrib import messages
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from main.models import PaymentCase, PassRegionPayment, CardPayment
from main.forms import PassRegionPaymentForm
import main.hello_asso


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
        
        missing_pass_region: int = payment_case.total_payments_required - payment_case.passregionpayment_set.exclude(payment_status=PassRegionPayment.PassRegionPaymentChoice.PAYMENT_REJECTED).count()
        PassRegionPaymentFormset = formset_factory(PassRegionPaymentForm, extra=missing_pass_region, max_num=missing_pass_region)

        return PassRegionPaymentFormset(data=self.request.POST if self.request.method == "POST" else None)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        if "formset" not in context:
            context["formset"] = self.get_formset()

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
        
        card_payment = CardPayment.objects.filter(
            payment_case=payment_case,
            redirect_url_expires_at__gt=timezone.now(),
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT,
        ).order_by("-pk").first()
        
        if card_payment is None:
            hello_asso_api = main.hello_asso.HelloAssoAPI()
            checkout_intent_id, redirect_url = hello_asso_api.create_checkout_intent(
                amount=payment_case.total_amount_required(),
                message="Coucou",
            )

            card_payment = CardPayment(
                payment_case=payment_case,
                redirect_url=redirect_url,
                checkout_intent_id=checkout_intent_id,
                redirect_url_expires_at=timezone.now() + timezone.timedelta(minutes=10), # HelloAsso API announces 15 minutes before expiration
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
                    return HttpResponseBadRequest(_("Identifiant de paiement manquant."))

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
                        payment_status=CardPayment.CardPaymentChoice.PAYMENT_SUCCESS
                    )
                    if updated:
                        messages.info(
                            request,
                            _("Paiement signalé comme réussi, en attente de vérification."),
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
