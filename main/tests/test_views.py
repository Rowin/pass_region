from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from main.models import CardPayment, PaymentCase
from main.views import CardPaymenRedirect


class CardPaymentRedirectTests(TestCase):
    @override_settings(
        ALLOWED_HOSTS=["127.0.0.1"],
        HELLO_ASSO_CALLBACK_BASE_URL="https://payments.example.com",
    )
    def test_checkout_callbacks_use_configured_public_base_url(self) -> None:
        request = RequestFactory().get(
            "/me/card-payment",
            HTTP_HOST="127.0.0.1:8000",
        )
        request.user = SimpleNamespace(is_authenticated=True)
        view = CardPaymenRedirect()
        view.setup(request)
        payment_case = PaymentCase()

        with (
            patch(
                "main.views.PaymentCase.objects.get",
                return_value=payment_case,
            ),
            patch(
                "main.views.CardPayment.objects.get",
                side_effect=CardPayment.DoesNotExist,
            ),
            patch("main.views.CardPayment.save"),
            patch(
                "main.views.main.hello_asso.HelloAssoAPI.create_checkout_intent",
                return_value="https://checkout.example.com/session",
            ) as create_checkout,
        ):
            result = view.get_redirect_url()

        callback_url = "https://payments.example.com/me/payments/"
        self.assertEqual(result, "https://checkout.example.com/session")
        create_checkout.assert_called_once_with(
            amount=35,
            message="Coucou",
            return_url=callback_url,
            error_url=callback_url,
            back_url=callback_url,
        )
