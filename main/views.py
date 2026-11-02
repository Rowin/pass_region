from typing import Any

from django.db.models import QuerySet, ObjectDoesNotExist
from django.db.models.base import Model as ModelBase
from django.views.generic import DetailView, CreateView, RedirectView
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.contrib import messages
from django.utils.translation import gettext as _

from main.models import PaymentCase, PassRegionPayment, CardPayment
from main.forms import PassRegionPaymentForm
import main.hello_asso


class PaymentCaseDetail(DetailView):
    model = PaymentCase
    context_object_name = "payment_case"

    def get_object(self, queryset: QuerySet[Any, Any] | None = ...) -> ModelBase:
        if self.request.user.is_authenticated:
            return PaymentCase.objects.get(user=self.request.user)
        else:
            raise PermissionDenied


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
    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        payment_case = PaymentCase.objects.get(user=self.request.user)
        try:
            card_payment = CardPayment.objects.get(
                payment_case=payment_case,
                redirect_url_expires_at__time__gt=timezone.now(),
                payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT,
            )
        except ObjectDoesNotExist:
            hello_asso_api = main.hello_asso.HelloAssoAPI()
            checkout_intent_id, redirect_url = hello_asso_api.create_checkout_intent(
                amount=35,
                message="Coucou",
            )

            card_payment = CardPayment(
                payment_case=payment_case,
                redirect_url=redirect_url,
                checkout_intent_id=checkout_intent_id,
                redirect_url_expires_at=timezone.now() + timezone.timedelta(minutes=15),
            )
            card_payment.save()

        return card_payment.redirect_url


class CardPaymentCallback(LoginRequiredMixin, RedirectView):
    def get_redirect_url(self):
        type = self.request.GET.get("type", "")
        match type:
            case "back":
                ...
            case "error" | "return":
                checkout_intent_id = self.request.GET.get("checkoutIntentId", "")
                card_payment = CardPayment.objects.get(
                    checkout_intent_id=checkout_intent_id
                )

                if self.request.GET.get("code", "") == "succeeded":
                    card_payment.payment_status = (
                        CardPayment.CardPaymentChoice.PAYMENT_SUCCESS
                    )
                    messages.success(self.request, _("Paiement réussi"))

                else:
                    card_payment.payment_status = (
                        CardPayment.CardPaymentChoice.PAYMENT_FAILED
                    )
                    messages.error(self.request, _("Paiement échoué !"))

                card_payment.save()

            case _:
                raise ValueError()

        return reverse("payment-case")
