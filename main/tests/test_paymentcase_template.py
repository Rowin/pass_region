from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from bs4 import BeautifulSoup
from django.forms import formset_factory
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from main.forms import PassRegionPaymentForm
from main.models import PassRegionPayment


class PaymentCaseTemplateTests(SimpleTestCase):
    def setUp(self) -> None:
        self.formset_class = formset_factory(PassRegionPaymentForm, extra=2)
        self.context = {
            "payment_case": SimpleNamespace(
                user=SimpleNamespace(first_name="Camille", last_name="Martin"),
                organization=SimpleNamespace(copay_amount_per_candidate=Decimal("35")),
                total_payments_required=2,
                total_amount_required=Decimal("70"),
                passregionpayment_set=SimpleNamespace(all=lambda: []),
            ),
            "session": SimpleNamespace(
                session_number="158726", date=None, location=None
            ),
            "formset": self.formset_class(),
        }

    def render_page(self) -> BeautifulSoup:
        html = render_to_string(
            "main/paymentcase_detail.html",
            self.context,
            request=RequestFactory().get(reverse("payment-case")),
        )
        return BeautifulSoup(html, "html.parser")

    def test_fields_have_unique_labels_and_associated_instructions(self) -> None:
        page = self.render_page()
        fields = page.select(".holder-fields input")
        self.assertEqual(len(fields), 8)
        ids = [element["id"] for element in page.select("[id]")]
        self.assertEqual(len(ids), len(set(ids)))
        for field in fields:
            with self.subTest(field=field["name"]):
                label = page.find("label", attrs={"for": field["id"]})
                self.assertIsNotNone(label)
                self.assertTrue(label.get_text(strip=True))
                for description_id in field.get("aria-describedby", "").split():
                    self.assertIsNotNone(page.find(id=description_id))
        pin = page.find("input", attrs={"name": "form-0-card_pin"})
        self.assertEqual(pin["type"], "password")
        self.assertEqual(pin["inputmode"], "numeric")
        self.assertIn(
            "4 chiffres", page.find("label", attrs={"for": pin["id"]}).get_text()
        )
        self.assertEqual(page.html["lang"], "fr")
        self.assertIn("Non communiqu", page.get_text())
        self.assertIsNotNone(
            page.select_one('form[action="%s"]' % reverse("card-payment"))
        )

    def test_errors_link_to_invalid_fields_without_redisplaying_pin(self) -> None:
        self.context["formset"] = self.formset_class(
            data={
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-0-holder_firstname": "Camille",
                "form-0-holder_lastname": "",
                "form-0-card_number": "",
                "form-0-card_pin": "12",
            }
        )
        self.assertFalse(self.context["formset"].is_valid())

        page = self.render_page()

        summary = page.select_one('.error-summary[role="alert"]')
        self.assertIsNotNone(summary)
        for name in ("holder_lastname", "card_number", "card_pin"):
            field = page.find("input", attrs={"name": f"form-0-{name}"})
            self.assertEqual(field["aria-invalid"], "true")
            self.assertIsNotNone(summary.find("a", href=f'#{field["id"]}'))
            for description_id in field["aria-describedby"].split():
                self.assertIsNotNone(page.find(id=description_id))
        self.assertIsNone(
            page.find("input", attrs={"name": "form-0-card_pin"}).get("value")
        )
        self.assertEqual(
            page.find("input", attrs={"name": "form-0-holder_firstname"})["value"],
            "Camille",
        )

    def test_checkout_explains_the_optional_helloasso_contribution_before_payment(
        self,
    ) -> None:
        page = self.render_page()
        checkout = page.find("form", action=reverse("card-payment"))
        notices = [
            page.find(id=description_id)
            for description_id in checkout["aria-describedby"].split()
        ]

        self.assertTrue(all(notice is not None for notice in notices))
        contribution = page.find(id="helloasso-contribution")
        self.assertEqual(
            contribution.get_text(),
            "Le modèle solidaire de HelloAsso garantit que 100% de votre paiement "
            "sera versé à l'association choisie. Vous pouvez soutenir l'aide "
            "qu'ils apportent aux associations en laissant une contribution "
            "volontaire à HelloAsso au moment de votre paiement.",
        )
        self.assertEqual(contribution.find_parent("form"), checkout)
        self.assertEqual(contribution.find_next("button"), checkout.find("button"))
        self.assertIsNone(checkout.find_parent("article"))
        self.assertIsNotNone(checkout.find(id=checkout["aria-labelledby"]))
        self.assertIn("70", checkout.find("button").get_text())

    def test_recorded_cards_are_distinct_from_new_card_forms(self) -> None:
        payment = PassRegionPayment(
            holder_firstname="Camille",
            holder_lastname="Martin",
            card_number="001234567",
            payment_status=PassRegionPayment.PassRegionPaymentChoice.PAYMENT_APPROVED,
            comment="Validation terminee",
        )
        self.context["payment_case"].passregionpayment_set.all = lambda: [payment]
        self.context["formset"] = formset_factory(PassRegionPaymentForm, extra=0)()
        self.context["session"].date = date(2026, 11, 19)
        self.context["session"].location = "Grenoble"

        page = self.render_page()

        self.assertIn("001234567", page.select_one(".registered-payments").get_text())
        self.assertIn("Validation terminee", page.get_text())
        pass_region_form = page.find("form", action=reverse("payment-case"))
        self.assertIsNone(pass_region_form.find("button"))
        self.assertIsNone(page.find("h3", string="Pass Région à renseigner"))
        details = {
            item.dt.get_text(strip=True): item.dd.get_text(strip=True)
            for item in page.select(".session-details > div")
        }
        self.assertEqual(details["Lieu"], "Grenoble")
        self.assertIn("19", details["Date"])

        self.context["formset"] = formset_factory(PassRegionPaymentForm, extra=1)()
        page = self.render_page()
        heading = page.find("h3", string="Pass Région à renseigner")
        self.assertIsNotNone(heading)
        self.assertEqual(
            heading.find_next_sibling(),
            page.find("form", action=reverse("payment-case")),
        )
        self.assertIsNotNone(page.select_one(".registered-payments"))
