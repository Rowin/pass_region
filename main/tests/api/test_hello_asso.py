import ssl
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.timezone import timedelta
from probatio import Invalid

from main.hello_asso import (
    CHECKOUT_INTENT_RESPONSE_SCHEMA,
    TOKEN_RESPONSE_SCHEMA,
    HelloAssoAPI,
)
from main.models import APICredentialRecord, Organization
from main.utils import _RelaxedX509HTTPAdapter


@override_settings(
    BASE_URL="https://example.com",
)
class HelloAssoAPITests(TestCase):
    def setUp(self) -> None:
        """Create a client for each test case."""
        self.organization = Organization.objects.create(
            organization_name="Test organization",
            hello_asso_client_id="test-client-id",
            hello_asso_client_secret="test-client-secret",
            hello_asso_organization_slug="test-organization",
            copay_amount_per_candidate=Decimal("35.00"),
            copay_message="Payment",
        )
        self.api = HelloAssoAPI(self.organization)

    def test_token_schema_rejects_invalid_expiration_and_extra_fields(self) -> None:
        """Reject invalid expiration strings and undocumented token fields."""
        for expires_in in ("0", "-1", "1.5", ""):
            with self.subTest(expires_in=expires_in):
                with self.assertRaises(Invalid):
                    TOKEN_RESPONSE_SCHEMA(
                        {
                            "access_token": "access",
                            "refresh_token": "refresh",
                            "expires_in": expires_in,
                        }
                    )
        for expires_in in ("3600", 3600):
            with self.subTest(expires_in=expires_in):
                result = TOKEN_RESPONSE_SCHEMA(
                    {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_in": expires_in,
                    }
                )
                self.assertEqual(result["expires_in"], expires_in)
        with self.assertRaises(Invalid):
            TOKEN_RESPONSE_SCHEMA(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": "3600",
                    "unknown": "value",
                }
            )

    def test_checkout_schema_rejects_null_url_and_extra_fields(self) -> None:
        """Reject unusable redirect URLs and undocumented checkout fields."""
        for payload in (
            {"id": 123, "redirectUrl": None},
            {"id": 123, "redirectUrl": ""},
            {"id": 123, "redirectUrl": "https://example.com", "unknown": "value"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(Invalid):
                    CHECKOUT_INTENT_RESPONSE_SCHEMA(payload)

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
        _, redirect_url = self.api.create_checkout_intent(
            amount,
            message,
        )
        return redirect_url

    def test_adapter_relaxes_strict_chain_check_but_keeps_tls_verification(
        self,
    ) -> None:
        adapter = _RelaxedX509HTTPAdapter()
        request = requests.Request("GET", HelloAssoAPI.AUTH_URL).prepare()
        _, pool_kwargs = adapter.build_connection_pool_key_attributes(
            request, verify=True
        )
        context = pool_kwargs["ssl_context"]

        self.assertFalse(context.verify_flags & ssl.VERIFY_X509_STRICT)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    @override_settings(DEBUG=False)
    @patch("main.hello_asso._RelaxedX509HTTPAdapter")
    @patch("main.hello_asso.requests.Session.post")
    def test_production_does_not_mount_relaxed_tls_adapter(
        self,
        post: Mock,
        adapter: Mock,
    ) -> None:
        post.return_value = self.response({"result": "ok"})

        self.api._request_json("https://example.com", headers={})

        adapter.assert_not_called()

    @patch("main.hello_asso.requests.Session.post")
    def test_http_error_logs_response_details_without_request_headers(
        self,
        post: Mock,
    ) -> None:
        response = self.response({"message": "amount is invalid"})
        response.status_code = 400
        response.text = '{"message":"amount is invalid"}'
        response.raise_for_status.side_effect = requests.HTTPError("Bad Request")
        post.return_value = response

        with self.assertLogs("main.hello_asso", level="WARNING") as captured:
            with self.assertRaises(requests.HTTPError):
                self.api._request_json(
                    "https://api.helloasso-sandbox.com/v5/checkout-intents",
                    headers={"Authorization": "Bearer do-not-log"},
                )

        log_output = "\n".join(captured.output)
        self.assertIn("HTTP 400", log_output)
        self.assertIn("amount is invalid", log_output)
        self.assertNotIn("do-not-log", log_output)

    @patch("main.hello_asso.requests.Session.post")
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
                "backUrl": self.api.get_callback_url("back"),
                "errorUrl": self.api.get_callback_url("error"),
                "returnUrl": self.api.get_callback_url("return"),
                "containsDonation": False,
            },
        )
        self.assertEqual(
            checkout_call.kwargs["headers"]["Authorization"],
            "Bearer new-access-token",
        )
        self.assertEqual(APICredentialRecord.objects.count(), 1)
        credential = APICredentialRecord.objects.get()
        self.assertEqual(credential.organization, self.organization)
        self.assertEqual(credential.refresh_token, "new-refresh-token")
        self.assertEqual(credential.access_token, "new-access-token")

    @patch("main.hello_asso.requests.Session.post")
    def test_checkout_uses_organization_slug(self, post: Mock) -> None:
        """Build checkout requests from the organization rather than global settings."""
        self.organization.hello_asso_organization_slug = "another-slug"
        APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="cached-refresh-token",
            access_token="cached-access-token",
            access_token_expires_at=timezone.now() + timedelta(minutes=10),
        )
        post.return_value = self.response(
            {"id": 123, "redirectUrl": "https://www.helloasso.com/checkout/donation"}
        )

        redirect_url = self.create_checkout(5, "Donation")

        self.assertEqual(redirect_url, "https://www.helloasso.com/checkout/donation")
        self.assertEqual(
            post.call_args.args[0],
            f"{HelloAssoAPI.API_URL}/organizations/another-slug/checkout-intents",
        )

    @patch("main.hello_asso.requests.Session.post")
    def test_valid_access_token_is_reused_without_authentication_request(
        self,
        post: Mock,
    ) -> None:
        """Check that a sufficiently long-lived access token is reused."""
        APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="cached-refresh-token",
            access_token="cached-access-token",
            access_token_expires_at=timezone.now() + timedelta(minutes=10),
        )
        post.return_value = self.response(
            {"id": 123, "redirectUrl": "https://www.helloasso.com/checkout/cached"}
        )

        redirect_url = self.create_checkout(5, "Payment")

        self.assertEqual(redirect_url, "https://www.helloasso.com/checkout/cached")
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer cached-access-token",
        )

    @patch("main.hello_asso.requests.Session.post")
    def test_other_organizations_token_is_not_reused(self, post: Mock) -> None:
        """A valid foreign token must not bypass this organization's authentication."""
        other = Organization.objects.create(
            organization_name="Other organization",
            hello_asso_client_id="other-client",
            hello_asso_client_secret="other-secret",
            hello_asso_organization_slug="other-slug",
            copay_amount_per_candidate=Decimal("35.00"),
            copay_message="Other payment",
        )
        foreign = APICredentialRecord.objects.create(
            organization=other,
            refresh_token="foreign-refresh",
            access_token="foreign-access",
            access_token_expires_at=timezone.now() + timedelta(hours=1),
        )
        post.side_effect = [
            self.response(
                {
                    "access_token": "own-access",
                    "refresh_token": "own-refresh",
                    "expires_in": "3600",
                }
            ),
            self.response({"id": 123, "redirectUrl": "https://example.com/checkout"}),
        ]

        self.create_checkout(5, "Payment")

        self.assertEqual(
            post.call_args_list[0].kwargs["data"],
            {
                "grant_type": "client_credentials",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
            },
        )
        own = APICredentialRecord.objects.get(organization=self.organization)
        self.assertEqual(own.access_token, "own-access")
        foreign.refresh_from_db()
        self.assertEqual(foreign.access_token, "foreign-access")
        self.assertEqual(foreign.refresh_token, "foreign-refresh")

    @patch("main.hello_asso.requests.Session.post")
    def test_expired_access_token_is_refreshed_and_credentials_are_updated(
        self,
        post: Mock,
    ) -> None:
        """Check form-encoded refresh and persistence of the rotated token pair."""
        credential = APICredentialRecord.objects.create(
            organization=self.organization,
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
                {
                    "id": 123,
                    "redirectUrl": "https://www.helloasso.com/checkout/refreshed",
                }
            ),
        ]

        self.create_checkout(5, "Payment")

        refresh_call = post.call_args_list[0]
        self.assertEqual(refresh_call.args[0], HelloAssoAPI.AUTH_URL)
        self.assertEqual(
            refresh_call.kwargs["data"],
            {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh-token",
            },
        )
        self.assertIsNone(refresh_call.kwargs["json"])
        self.assertEqual(
            refresh_call.kwargs["headers"]["Content-Type"],
            "application/x-www-form-urlencoded",
        )
        credential.refresh_from_db()
        self.assertEqual(credential.access_token, "refreshed-access-token")
        self.assertEqual(credential.refresh_token, "rotated-refresh-token")

    @patch("main.hello_asso.requests.Session.post")
    def test_refresh_http_error_falls_back_to_full_auth_once(self, post: Mock) -> None:
        """Recover from any refresh HTTP error and replace the stored token pair."""
        credential = APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="rejected-refresh-token",
            access_token="expired-access-token",
            access_token_expires_at=timezone.now() - timedelta(seconds=1),
        )
        rejected = self.response({})
        rejected.status_code = 500
        rejected.text = "Authentication failed"
        rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
        post.side_effect = [
            rejected,
            self.response(
                {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": "3600",
                }
            ),
            self.response(
                {"id": 123, "redirectUrl": "https://www.helloasso.com/checkout/new"}
            ),
        ]

        self.create_checkout(5, "Payment")

        self.assertEqual(post.call_count, 3)
        self.assertEqual(
            post.call_args_list[0].kwargs["data"],
            {
                "grant_type": "refresh_token",
                "refresh_token": "rejected-refresh-token",
            },
        )
        self.assertEqual(
            post.call_args_list[1].kwargs["data"],
            {
                "grant_type": "client_credentials",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
            },
        )
        credential.refresh_from_db()
        self.assertEqual(credential.access_token, "new-access-token")
        self.assertEqual(credential.refresh_token, "new-refresh-token")
        self.assertEqual(APICredentialRecord.objects.count(), 1)

    @patch("main.hello_asso.requests.Session.post")
    def test_full_auth_failure_after_refresh_is_not_retried(self, post: Mock) -> None:
        """Propagate the second HTTP error without changing stored credentials."""
        credential = APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="old-refresh-token",
            access_token="expired-access-token",
            access_token_expires_at=timezone.now() - timedelta(seconds=1),
        )
        rejected = self.response({})
        rejected.status_code = 401
        rejected.text = "Authentication failed"
        error = requests.HTTPError(response=rejected)
        rejected.raise_for_status.side_effect = error
        post.return_value = rejected

        with self.assertRaises(requests.HTTPError) as caught:
            self.create_checkout(5, "Payment")

        self.assertIs(caught.exception, error)
        self.assertEqual(post.call_count, 2)
        credential.refresh_from_db()
        self.assertEqual(credential.refresh_token, "old-refresh-token")
        self.assertEqual(credential.access_token, "expired-access-token")

    @patch("main.hello_asso.requests.Session.post")
    def test_refresh_network_error_does_not_trigger_full_auth(self, post: Mock) -> None:
        """A transport failure does not fall back to client credentials."""
        APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="old-refresh-token",
            access_token="expired-access-token",
            access_token_expires_at=timezone.now() - timedelta(seconds=1),
        )
        post.side_effect = requests.Timeout("Request timed out")

        with self.assertRaises(requests.Timeout):
            self.create_checkout(5, "Payment")

        post.assert_called_once()

    @patch("main.hello_asso.requests.Session.post")
    def test_full_auth_fallback_requires_a_new_refresh_token(self, post: Mock) -> None:
        """Do not reuse the rejected refresh token after incomplete full auth."""
        credential = APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="old-refresh-token",
            access_token="expired-access-token",
            access_token_expires_at=timezone.now() - timedelta(seconds=1),
        )
        post.side_effect = [
            requests.HTTPError("Refresh rejected"),
            self.response({"access_token": "new-access-token", "expires_in": "3600"}),
        ]

        with self.assertRaises(Invalid):
            self.create_checkout(5, "Payment")

        self.assertEqual(post.call_count, 2)
        credential.refresh_from_db()
        self.assertEqual(credential.refresh_token, "old-refresh-token")
        self.assertEqual(credential.access_token, "expired-access-token")

    @patch("main.hello_asso.requests.Session.post")
    def test_refresh_requires_a_new_refresh_token(self, post: Mock) -> None:
        """Reject incomplete refresh responses without modifying stored credentials."""
        credential = APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="old-refresh-token",
            access_token="expired-access-token",
            access_token_expires_at=timezone.now() - timedelta(seconds=1),
        )
        for refresh_token in (None, "", 123):
            with self.subTest(refresh_token=refresh_token):
                post.reset_mock()
                payload: dict[str, object] = {
                    "access_token": "new-access-token",
                    "expires_in": "3600",
                }
                if refresh_token is not None:
                    payload["refresh_token"] = refresh_token
                post.return_value = self.response(payload)

                with self.assertRaises(Invalid):
                    self.create_checkout(5, "Payment")

                post.assert_called_once()
                credential.refresh_from_db()
                self.assertEqual(credential.refresh_token, "old-refresh-token")
                self.assertEqual(credential.access_token, "expired-access-token")

    @patch("main.hello_asso.requests.Session.post")
    def test_missing_client_credentials_raise_configuration_error(
        self,
        post: Mock,
    ) -> None:
        """Check missing client credentials fail before any HTTP request."""
        self.organization.hello_asso_client_id = ""
        self.organization.hello_asso_client_secret = ""
        with self.assertRaises(ImproperlyConfigured):
            self.create_checkout(5, "Payment")

        post.assert_not_called()

    @patch("main.hello_asso.requests.Session.post")
    def test_fractional_cent_amount_is_rejected_before_request(
        self,
        post: Mock,
    ) -> None:
        """Check amounts with fractional cents are rejected before the API call."""
        with self.assertRaises(ValueError):
            self.create_checkout(Decimal("1.001"), "Payment")

        post.assert_not_called()

    @patch("main.hello_asso.requests.Session.post")
    def test_empty_message_is_rejected_before_request(self, post: Mock) -> None:
        """Check an empty payment label is rejected before the API call."""
        with self.assertRaises(ValueError):
            self.create_checkout(1, "")

        post.assert_not_called()

    @patch("main.hello_asso.requests.Session.post")
    def test_missing_redirect_url_raises_validation_error(self, post: Mock) -> None:
        """Check a checkout response without a redirect URL is rejected."""
        APICredentialRecord.objects.create(
            organization=self.organization,
            refresh_token="cached-refresh-token",
            access_token="cached-access-token",
            access_token_expires_at=timezone.now() + timedelta(minutes=10),
        )
        post.return_value = self.response({"id": 123})

        with self.assertRaises(Invalid):
            self.create_checkout(1, "Payment")

    @patch("main.hello_asso.requests.Session.post")
    def test_missing_organization_slug_raises_configuration_error(
        self,
        post: Mock,
    ) -> None:
        """Check a missing organization slug fails before any HTTP request."""
        self.organization.hello_asso_organization_slug = ""
        with self.assertRaises(ImproperlyConfigured):
            self.create_checkout(5, "Payment")

        post.assert_not_called()
