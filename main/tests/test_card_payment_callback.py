from unittest.mock import Mock, patch

from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.messages.storage.base import Message
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import Http404, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from main.hello_asso import HelloAssoAPI
from main.models import CardPayment
from main.views import CardPaymentCallback


class CardPaymentCallbackTests(SimpleTestCase):
    """Verify browser-return validation and guarded updates without API or DB calls."""

    def setUp(self) -> None:
        """Provide a logged-in request and isolated payment querysets."""
        self.factory = RequestFactory()
        self.user = Mock(is_authenticated=True)
        self.payment = Mock()
        self.lookup = self.enterContext(
            patch("main.views.get_object_or_404", return_value=self.payment)
        )
        self.pending_payments = Mock()
        self.pending_payments.update.return_value = 1
        self.manager = self.enterContext(
            patch(
                "main.views.CardPayment.objects.filter",
                return_value=self.pending_payments,
            )
        )
        self.post = self.enterContext(patch("main.hello_asso.requests.post"))

    def callback(
        self, callback_type: str, query: str = ""
    ) -> tuple[HttpResponse, list[Message]]:
        """Dispatch a browser return with session-backed message storage."""
        url = reverse("card-payment-return", kwargs={"callback_type": callback_type})
        request = self.factory.get(f"{url}?{query}")
        request.user = self.user
        SessionMiddleware(lambda _: HttpResponse()).process_request(request)
        MessageMiddleware(lambda _: HttpResponse()).process_request(request)
        match = resolve(url)
        response = match.func(request, **match.kwargs)
        self.post.assert_not_called()
        return response, list(get_messages(request))

    def test_success_is_owned_provisional_and_atomic(self) -> None:
        """A forged success can only record an owned pending attempt as reported."""
        response, notifications = self.callback(
            "return", "checkoutIntentId=123&code=succeeded"
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("payment-case"))
        self.lookup.assert_called_once_with(
            CardPayment,
            checkout_intent_id="123", payment_case__user=self.user
        )
        self.manager.assert_called_once_with(
            checkout_intent_id="123",
            payment_case__user=self.user,
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT
        )
        self.pending_payments.update.assert_called_once_with(
            payment_status=CardPayment.CardPaymentChoice.PAYMENT_SUCCESS
        )
        self.payment.save.assert_not_called()
        self.assertEqual(len(notifications), 1)
        self.assertIn("vérification", str(notifications[0]))

    def test_replayed_or_terminal_success_does_not_emit_success_message(self) -> None:
        """A conditional update matching no pending attempt causes no further writes."""
        self.pending_payments.update.return_value = 0
        response, notifications = self.callback(
            "return", "checkoutIntentId=123&code=succeeded"
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(notifications, [])
        self.payment.save.assert_not_called()
        self.manager.assert_called_once_with(
            checkout_intent_id="123",
            payment_case__user=self.user,
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT
        )

    def test_unknown_or_other_users_payment_is_not_found(self) -> None:
        """An ownership-scoped lookup hides unknown and other users' attempts."""
        for callback_type in ("return", "error"):
            with self.subTest(callback_type=callback_type):
                self.lookup.side_effect = Http404
                with self.assertRaises(Http404):
                    self.callback(
                        callback_type, "checkoutIntentId=123&code=succeeded"
                    )
                self.pending_payments.update.assert_not_called()

    def test_error_marks_only_waiting_payments_as_failed(self) -> None:
        """Error returns fail a pending attempt without overwriting other states."""
        response, notifications = self.callback("error", "checkoutIntentId=123")
        self.assertEqual(response.status_code, 302)
        self.manager.assert_called_once_with(
            checkout_intent_id="123",
            payment_case__user=self.user,
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT
        )
        self.pending_payments.update.assert_called_once_with(
            payment_status=CardPayment.CardPaymentChoice.PAYMENT_FAILED
        )
        self.assertEqual(len(notifications), 1)
        self.assertIn("échoué", str(notifications[0]))
        self.payment.save.assert_not_called()

    def test_error_preserves_provisional_and_terminal_states(self) -> None:
        """An error matching no waiting payment neither writes nor announces failure."""
        self.pending_payments.update.return_value = 0
        response, notifications = self.callback("error", "checkoutIntentId=123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(notifications, [])
        self.manager.assert_called_once_with(
            checkout_intent_id="123",
            payment_case__user=self.user,
            payment_status=CardPayment.CardPaymentChoice.WAITING_PAYMENT
        )
        self.payment.save.assert_not_called()

    def test_back_redirects_silently_without_accessing_payments(self) -> None:
        """Back navigation only redirects, regardless of supplied checkout parameters."""
        for query in (
            "",
            "checkoutIntentId=123&code=succeeded",
            "checkoutIntentId=",
        ):
            with self.subTest(query=query):
                response, notifications = self.callback("back", query)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], reverse("payment-case"))
                self.assertEqual(notifications, [])
                self.manager.assert_not_called()
                self.pending_payments.update.assert_not_called()
                self.payment.save.assert_not_called()

    def test_checkout_id_is_passed_to_lookup_without_format_restrictions(self) -> None:
        """Treat external checkout identifiers as opaque values."""
        for identifier in ("abc", "-1", "0", "2147483648", "12345678901", "id-123"):
            with self.subTest(identifier=identifier):
                self.lookup.reset_mock()
                response, _ = self.callback(
                    "return", f"checkoutIntentId={identifier}&code=succeeded"
                )
                self.assertEqual(response.status_code, 302)
                self.lookup.assert_called_once_with(
                    CardPayment,
                    checkout_intent_id=identifier, payment_case__user=self.user
                )

    def test_malformed_callbacks_are_bad_requests(self) -> None:
        """Reject missing, malformed and ambiguous inputs before accessing payments."""
        for callback_type, query in (
            ("unknown", ""),
            ("return", ""),
            ("error", ""),
            ("return", "checkoutIntentId="),
            ("return", "checkoutIntentId=123&checkoutIntentId=456"),
            ("return", "checkoutIntentId=123&code=succeeded&code=failed"),
        ):
            with self.subTest(query=query):
                response, notifications = self.callback(callback_type, query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(notifications, [])
                self.lookup.assert_not_called()
                self.manager.assert_not_called()

    def test_query_type_cannot_override_path_type(self) -> None:
        """The route selects the outcome even when query parameters claim another type."""
        response, notifications = self.callback(
            "back", "type=return&type=error&checkoutIntentId=123&code=succeeded"
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(notifications, [])
        self.manager.assert_not_called()

    @override_settings(HELLO_ASSO_CALLBACK_BASE_URL="https://payments.example.com")
    def test_generated_callback_urls_use_path_types(self) -> None:
        """All three URLs supplied to Hello Asso resolve to the shared callback view."""
        api = HelloAssoAPI()
        for callback_type in ("back", "error", "return"):
            with self.subTest(callback_type=callback_type):
                path = reverse(
                    "card-payment-return", kwargs={"callback_type": callback_type}
                )
                self.assertEqual(
                    api.get_callback_url(callback_type),
                    f"https://payments.example.com{path}",
                )
                self.assertEqual(resolve(path).kwargs, {"callback_type": callback_type})

    def test_head_cannot_change_payment_status(self) -> None:
        """HEAD must not inherit the GET handler's status-changing behavior."""
        request = self.factory.head(
            reverse("card-payment-return", kwargs={"callback_type": "return"})
        )
        request.user = self.user
        response = CardPaymentCallback.as_view()(request, callback_type="return")

        self.assertEqual(response.status_code, 405)
        self.manager.assert_not_called()

    def test_anonymous_return_requires_login(self) -> None:
        """Anonymous browser returns cannot read or update payment attempts."""
        request = self.factory.get(
            reverse("card-payment-return", kwargs={"callback_type": "return"}),
            {"checkoutIntentId": "123", "code": "succeeded"},
        )
        request.user = Mock(is_authenticated=False)
        response = CardPaymentCallback.as_view()(request, callback_type="return")

        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response["Location"])
        self.manager.assert_not_called()
