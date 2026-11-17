import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from main.models import CardPayment, Organization, PaymentCase, StaffUser
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


class WebhookTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            organization_name="APC TEST",
            hello_asso_client_id="client_id",
            hello_asso_client_secret="client_secret",
            hello_asso_organization_slug="slug",
            copay_amount_per_candidate="100",
            copay_message="message",
        )

        user = get_user_model().objects.create_user(
            username="username",
            first_name="Firstname",
            last_name="Lastname",
            email="email@email.test",
            password=None,
            is_staff=False,
            is_superuser=False,
        )

        staff_user = StaffUser.objects.create(user=user)
        staff_user.organization.add(self.org)

        payment_case = PaymentCase.objects.create(
            user=user, session_number=123456, organization=self.org
        )
        self.card_payment = CardPayment.objects.create(
            checkout_intent_id=12345,
            redirect_url="example.com",
            redirect_url_expires_at=timezone.now(),
            payment_case=payment_case,
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT,
        )

        self.client = Client()

    def test_successful_webhook(self):
        response = self.client.post(
            reverse("webhook", args=[self.org.webhook_uuid]),
            content_type="application/json",
            data={
                "data": {
                    "payments": [{"state": "Authorized"}],
                    "checkoutIntentId": 12345,
                },
                "eventType": "Order",
            },
        )
        self.card_payment.refresh_from_db()
        self.assertEqual(
            self.card_payment.payment_status,
            CardPayment.CardPaymentChoice.PAYMENT_CONFIRMED,
        )
        self.assertEqual(response.status_code, 200)

    def test_invalid_webhook(self):
        response = self.client.post(
            reverse("webhook", args=[uuid.uuid1()]),
            content_type="application/json",
            data={
                "data": {
                    "payments": [{"state": "Authorized"}],
                    "checkoutIntentId": 12345,
                },
                "eventType": "Order",
            },
        )

        self.assertEqual(response.status_code, 404)
