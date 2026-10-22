from decimal import Decimal
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.timezone import timedelta

from main.hello_asso import HelloAssoAPI
from main.models import APICredentialRecord


@override_settings(
    HELLO_ASSO_CLIENT_ID="test-client-id",
    HELLO_ASSO_CLIENT_SECRET="test-client-secret",
    HELLO_ASSO_ORGANIZATION_SLUG="test-organization",
)
class HelloAssoAPITests(TestCase):
    def setUp(self) -> None:
        """Create a client for each test case."""
        self.api = HelloAssoAPI()

    @staticmethod
    def response(payload: dict[str, object]) -> Mock:
        """Build a mock HTTP response that returns the given JSON payload."""
        response = Mock()
        response.json.return_value = payload
        return response

    def create_checkout(
        self,
        amount: Decimal | int | float,
        message: str,
    ) -> str:
        """Create a checkout using the shared redirect URLs for the tests."""
        return self.api.create_checkout_intent(
            amount,
            message,
            back_url="https://example.com/back",
            error_url="https://example.com/error",
            return_url="https://example.com/return",
        )

    @patch("main.hello_asso.requests.post")
    def test_checkout_uses_client_credentials_and_returns_redirect_url(
        self,
        post: Mock,
    ) -> None:
        """Check initial authentication, checkout payload, token storage and URL."""
        post.side_effect = [
            self.response(
                {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": "3600",
                }
            ),
            self.response(
                {
                    "id": 123,
                    "redirectUrl": "https://www.helloasso.com/checkout/123",
                }
            ),
        ]

        redirect_url = self.create_checkout(Decimal("12.34"), "Payment message")

        self.assertEqual(redirect_url, "https://www.helloasso.com/checkout/123")
        self.assertEqual(post.call_count, 2)
        auth_call, checkout_call = post.call_args_list
        self.assertEqual(auth_call.args[0], HelloAssoAPI.AUTH_URL)
        self.assertEqual(
            auth_call.kwargs["data"],
            {
                "grant_type": "client_credentials",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
            },
        )
        self.assertEqual(
            checkout_call.args[0],
            f"{HelloAssoAPI.API_URL}/organizations/test-organization/checkout-intents",
        )
        self.assertEqual(
            checkout_call.kwargs["json"],
            {
                "totalAmount": 1234,
                "initialAmount": 1234,
                "itemName": "Payment message",
                "backUrl": "https://example.com/back",
                "errorUrl": "https://example.com/error",
                "returnUrl": "https://example.com/return",
                "containsDonation": False,
            },
        )
        self.assertEqual(
            checkout_call.kwargs["headers"]["Authorization"],
            "Bearer new-access-token",
        )
        self.assertEqual(APICredentialRecord.objects.count(), 1)
        credential = APICredentialRecord.objects.get()
        self.assertEqual(credential.refresh_token, "new-refresh-token")
        self.assertEqual(credential.access_token, "new-access-token")

    @patch("main.hello_asso.requests.post")
    def test_checkout_can_enable_donations(self, post: Mock) -> None:
        """Check that the optional donation flag is forwarded to Hello Asso."""
        APICredentialRecord.objects.create(
            refresh_token="cached-refresh-token",
            access_token="cached-access-token",
            access_token_expires_at=timezone.now() + timedelta(minutes=10),
        )
        post.return_value = self.response(
            {"redirectUrl": "https://www.helloasso.com/checkout/donation"}
        )

        redirect_url = self.api.create_checkout_intent(
            5,
            "Donation",
            back_url="https://example.com/back",
            error_url="https://example.com/error",
            return_url="https://example.com/return",
            contains_donation=True,
        )

        self.assertEqual(redirect_url, "https://www.helloasso.com/checkout/donation")
        self.assertTrue(post.call_args.kwargs["json"]["containsDonation"])

    @patch("main.hello_asso.requests.post")
    def test_valid_access_token_is_reused_without_authentication_request(
        self,
        post: Mock,
    ) -> None:
        """Check that a sufficiently long-lived access token is reused."""
        APICredentialRecord.objects.create(
            refresh_token="cached-refresh-token",
            access_token="cached-access-token",
            access_token_expires_at=timezone.now() + timedelta(minutes=10),
        )
        post.return_value = self.response(
            {"redirectUrl": "https://www.helloasso.com/checkout/cached"}
        )

        redirect_url = self.create_checkout(5, "Payment")

        self.assertEqual(redirect_url, "https://www.helloasso.com/checkout/cached")
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer cached-access-token",
        )

    @patch("main.hello_asso.requests.post")
    def test_expired_access_token_is_refreshed_and_credentials_are_updated(
        self,
        post: Mock,
    ) -> None:
        """Check refresh-token use and persistence of the rotated token pair."""
        credential = APICredentialRecord.objects.create(
            refresh_token="old-refresh-token",
            access_token="expired-access-token",
            access_token_expires_at=timezone.now() - timedelta(seconds=1),
        )
        post.side_effect = [
            self.response(
                {
                    "access_token": "refreshed-access-token",
                    "refresh_token": "rotated-refresh-token",
                    "expires_in": "3600",
                }
            ),
            self.response(
                {"redirectUrl": "https://www.helloasso.com/checkout/refreshed"}
            ),
        ]

        self.create_checkout(5, "Payment")

        refresh_call = post.call_args_list[0]
        self.assertEqual(refresh_call.args[0], HelloAssoAPI.AUTH_URL)
        self.assertEqual(
            refresh_call.kwargs["json"],
            {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh-token",
            },
        )
        credential.refresh_from_db()
        self.assertEqual(credential.access_token, "refreshed-access-token")
        self.assertEqual(credential.refresh_token, "rotated-refresh-token")

    @override_settings(HELLO_ASSO_CLIENT_ID="", HELLO_ASSO_CLIENT_SECRET="")
    @patch("main.hello_asso.requests.post")
    def test_missing_client_credentials_raise_configuration_error(
        self,
        post: Mock,
    ) -> None:
        """Check missing client credentials fail before any HTTP request."""
        with self.assertRaises(ImproperlyConfigured):
            self.create_checkout(5, "Payment")

        post.assert_not_called()

    @patch("main.hello_asso.requests.post")
    def test_fractional_cent_amount_is_rejected_before_request(
        self,
        post: Mock,
    ) -> None:
        """Check amounts with fractional cents are rejected before the API call."""
        with self.assertRaises(ValueError):
            self.create_checkout(Decimal("1.001"), "Payment")

        post.assert_not_called()

    @patch("main.hello_asso.requests.post")
    def test_empty_message_is_rejected_before_request(self, post: Mock) -> None:
        """Check an empty payment label is rejected before the API call."""
        with self.assertRaises(ValueError):
            self.create_checkout(1, "")

        post.assert_not_called()

    @patch("main.hello_asso.requests.post")
    def test_missing_redirect_url_raises_value_error(self, post: Mock) -> None:
        """Check a checkout response without a redirect URL is rejected."""
        APICredentialRecord.objects.create(
            refresh_token="cached-refresh-token",
            access_token="cached-access-token",
            access_token_expires_at=timezone.now() + timedelta(minutes=10),
        )
        post.return_value = self.response({"id": 123})

        with self.assertRaises(ValueError):
            self.create_checkout(1, "Payment")

    @override_settings(HELLO_ASSO_ORGANIZATION_SLUG="")
    @patch("main.hello_asso.requests.post")
    def test_missing_organization_slug_raises_configuration_error(
        self,
        post: Mock,
    ) -> None:
        """Check a missing organization slug fails before any HTTP request."""
        with self.assertRaises(ImproperlyConfigured):
            self.create_checkout(5, "Payment")

        post.assert_not_called()
