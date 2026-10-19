from django.views.generic import DetailView, CreateView
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin

from main.models import PaymentCase, PassRegionPayment
from main.forms import PassRegionPaymentForm

class PaymentCaseDetail(LoginRequiredMixin, DetailView):
    model = PaymentCase
    context_object_name = "payment_case"

class PassRegionPaymentCreate(LoginRequiredMixin, CreateView):
    model = PassRegionPayment
    form_class = PassRegionPaymentForm

    def get_success_url(self) -> str:
        return reverse("payment-case", kwargs={"pk":self.kwargs["pk"]})

    def form_valid(self, form: PassRegionPaymentForm):
        form.instance.payment_case = get_object_or_404(PaymentCase, pk=self.kwargs["pk"])
        form.instance.payment_status = PassRegionPayment.PassRegionPaymentChoice.WAITING_PAYMENT

        return super().form_valid(form)