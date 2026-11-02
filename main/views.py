from typing import Any, cast
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.db.models import QuerySet, ObjectDoesNotExist
from django.db.models.base import Model as ModelBase
from django.views.generic import DetailView, CreateView, RedirectView
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ImproperlyConfigured, PermissionDenied

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
        form.instance.payment_status = PassRegionPayment.PassRegionPaymentChoice.WAITING_PAYMENT

        return super().form_valid(form)

class CardPaymenRedirect(LoginRequiredMixin, RedirectView):
    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        payment_case = PaymentCase.objects.get(user=self.request.user)
        try:
            card_payment = CardPayment.objects.get(payment_case=payment_case)
        except ObjectDoesNotExist:
            hello_asso_api = main.hello_asso.HelloAssoAPI()
            callback_path = reverse("payment-case")
            callback_base_url = getattr(
                settings, "HELLO_ASSO_CALLBACK_BASE_URL", ""
            )
            if callback_base_url:
                parsed_base_url = urlsplit(callback_base_url)
                if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
                    raise ImproperlyConfigured(
                        "HELLO_ASSO_CALLBACK_BASE_URL must be an absolute HTTPS URL."
                    )
                payment_case_url = urljoin(
                    f"{callback_base_url.rstrip('/')}/",
                    callback_path.lstrip("/"),
                )
            else:
                payment_case_url = self.request.build_absolute_uri(callback_path)
            checkout_url = hello_asso_api.create_checkout_intent(
                amount=35,
                message="Coucou",
                return_url=payment_case_url,
                error_url=payment_case_url,
                back_url=payment_case_url,
            )

            card_payment = CardPayment(payment_case=payment_case, checkout_url=checkout_url)
            card_payment.save()

        return card_payment.checkout_url


        