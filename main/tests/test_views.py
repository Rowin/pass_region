import uuid
from decimal import Decimal
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
        BASE_URL="https://payments.example.com",
    )
    def test_checkout_uses_payment_case_amount_and_message(self) -> None:
        request = RequestFactory().get(
            "/me/card-payment",
            HTTP_HOST="127.0.0.1:8000",
        )
        request.user = SimpleNamespace(is_authenticated=True)
        view = CardPaymenRedirect()
        view.setup(request)
        organization = Organization(
            copay_amount_per_candidate=Decimal("35.00"), copay_message="Coucou"
        )
        payment_case = PaymentCase(pk=1, organization=organization)

        with (
            patch(
                "main.views.PaymentCase.objects.get",
                return_value=payment_case,
            ),
            patch(
                "main.views.CardPayment.objects.filter",
            ) as payments,
            patch("main.views.CardPayment.save"),
            patch(
                "main.views.main.hello_asso.HelloAssoAPI.create_checkout_intent",
                return_value=(123, "https://checkout.example.com/session"),
            ) as create_checkout,
        ):
            payments.return_value.order_by.return_value.first.return_value = None
            result = view.get_redirect_url()

        self.assertEqual(result, "https://checkout.example.com/session")
        create_checkout.assert_called_once_with(
            amount=Decimal("35.00"),
            message="Coucou",
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

    @patch(
        "main.views.notifications.send_credit_card_payment_confirmation_notification"
    )
    @patch.object(CardPayment, "save")
    def test_successful_webhook(self, save, notify):
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
        self.assertIsNotNone(self.card_payment.payment_confirmation_received_at)
        save.assert_not_called()
        notify.assert_called_once_with(self.card_payment.payment_case)
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
