from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from requests import ConnectionError, HTTPError, Timeout

from main.models import Session

SESSION_HTML = b"""
<span>01/01/2000</span>
<div class="fnpc-training-session--practical-info">
    <i data-icon="locationalt"></i>
    <span>
        <h3>Lieu de formation</h3>
        <span>2, impasse Jean Mac&#233;, 30900 N&#206;MES</span>
    </span>
</div>
<div class="fnpc-training-session--practical-info">
    <i data-icon="calendar"></i>
    <span>
        <h3>Dates de formation</h3>
        <span>19/11/2026 08:00 - 12:30</span><br>
        <span>20/11/2026 13:00 - 16:00</span><br>
    </span>
</div>
"""


class SessionManagerTests(TestCase):
    def test_existing_session_is_returned_without_fetching(self) -> None:
        existing = Session.objects.create(
            session_number="00123", location="Grenoble", date=date(2026, 11, 18)
        )

        with patch.object(Session.objects, "_fetch_session_data") as fetch:
            session = Session.objects.get_or_fetch("00123")

        self.assertEqual(session, existing)
        self.assertEqual(session.location, "Grenoble")
        self.assertEqual(session.date, date(2026, 11, 18))
        fetch.assert_not_called()

    def test_missing_session_is_saved_with_fetched_data_and_reused(self) -> None:
        with patch.object(
            Session.objects,
            "_fetch_session_data",
            return_value=("Grenoble", date(2027, 1, 15)),
        ) as fetch:
            session = Session.objects.get_or_fetch("00123")
            repeated = Session.objects.get_or_fetch("00123")

        fetch.assert_called_once_with("00123")
        self.assertEqual(repeated, session)
        session.refresh_from_db()
        self.assertEqual(session.session_number, "00123")
        self.assertEqual(session.location, "Grenoble")
        self.assertEqual(session.date, date(2027, 1, 15))
        self.assertEqual(Session.objects.count(), 1)

    def test_session_page_is_requested_and_parsed(self) -> None:
        with patch("main.models.requests.Session.get") as get:
            get.return_value.content = SESSION_HTML
            session = Session.objects.get_or_fetch("158726")

        get.assert_called_once_with(
            "https://formations.protection-civile.org/detail-formation/",
            params={"id_session": "158726"},
            timeout=10,
        )
        get.return_value.raise_for_status.assert_called_once_with()

        session.refresh_from_db()
        self.assertEqual(
            session.location, "2, impasse Jean Mac\u00e9, 30900 N\u00ceMES"
        )
        self.assertEqual(session.date, date(2026, 11, 19))

    def test_unusable_page_returns_session_without_details(self) -> None:
        pages = (
            b"<html>Session not found</html>",
            SESSION_HTML.replace(b"19/11/2026", b"31/02/2026"),
            SESSION_HTML.replace(b"19/11/2026 08:00 - 12:30", b""),
            SESSION_HTML.replace(b"2, impasse Jean Mac&#233;, 30900 N&#206;MES", b""),
        )
        for index, content in enumerate(pages):
            with self.subTest(content=content):
                with (
                    patch("main.models.requests.Session.get") as get,
                    self.assertLogs("main.models", level="WARNING"),
                ):
                    get.return_value.content = content
                    session = Session.objects.get_or_fetch(str(index))

                session.refresh_from_db()
                self.assertIsNone(session.location)
                self.assertIsNone(session.date)

    def test_http_error_is_checked_before_parsing(self) -> None:
        with (
            patch("main.models.requests.Session.get") as get,
            self.assertLogs("main.models", level="WARNING"),
        ):
            get.return_value.content = SESSION_HTML
            get.return_value.raise_for_status.side_effect = HTTPError("Unavailable")
            session = Session.objects.get_or_fetch("158726")

        session.refresh_from_db()
        self.assertIsNone(session.location)
        self.assertIsNone(session.date)

    def test_relaxed_tls_adapter_is_only_mounted_in_debug_mode(self) -> None:
        for debug in (True, False):
            with self.subTest(debug=debug):
                with (
                    override_settings(DEBUG=debug),
                    patch("main.models.requests.Session.get") as get,
                    patch("main.models._RelaxedX509HTTPAdapter") as adapter,
                    patch("main.models.requests.Session.mount") as mount,
                ):
                    get.return_value.content = SESSION_HTML
                    Session.objects._fetch_session_data("158726")

                if debug:
                    adapter.assert_called_once_with()
                    mount.assert_any_call("https://", adapter.return_value)
                else:
                    adapter.assert_not_called()

    def test_web_failure_returns_a_saved_session_without_optional_details(self) -> None:
        for index, error in enumerate((ConnectionError, HTTPError, Timeout)):
            session_number = str(index)
            with self.subTest(error=error):
                with (
                    patch.object(
                        Session.objects,
                        "_fetch_session_data",
                        side_effect=error("Failed"),
                    ) as fetch,
                    self.assertLogs("main.models", level="WARNING"),
                ):
                    session = Session.objects.get_or_fetch(session_number)
                    repeated = Session.objects.get_or_fetch(session_number)

                fetch.assert_called_once_with(session_number)
                self.assertEqual(repeated, session)
                session.refresh_from_db()
                self.assertEqual(session.session_number, session_number)
                self.assertIsNone(session.location)
                self.assertIsNone(session.date)

    def test_unexpected_fetch_error_is_not_silenced(self) -> None:
        with patch.object(
            Session.objects,
            "_fetch_session_data",
            side_effect=RuntimeError("Unexpected failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "Unexpected failure"):
                Session.objects.get_or_fetch("123")
