from typing import Any

from django.db.models import QuerySet
from django.db.models.base import Model as Model
from django.views.generic import DetailView, CreateView
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from main.models import PaymentCase, PassRegionPayment
from main.forms import PassRegionPaymentForm

class PaymentCaseDetail(DetailView):
    model = PaymentCase
    context_object_name = "payment_case"

    def get_object(self, queryset: QuerySet[Any, Any] | None = ...) -> Model:
        if self.request.user.is_authenticated:
            return self.request.user.paymentcase
        else:
            raise PermissionDenied

class PassRegionPaymentCreate(LoginRequiredMixin, CreateView):
    model = PassRegionPayment
    form_class = PassRegionPaymentForm

    def get_success_url(self) -> str:
        return reverse("payment-case")

    def form_valid(self, form: PassRegionPaymentForm):
        user = self.request.user

        form.instance.payment_case = user.paymentcase
        form.instance.payment_status = PassRegionPayment.PassRegionPaymentChoice.WAITING_PAYMENT

        return super().form_valid(form)