from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from main.models import Organization, PaymentCase, Session


def send_payment_creation_notification(payment_case: PaymentCase, link: str):
    """Send a notification to the customer with their authentication link after registration"""
    org: Organization = payment_case.organization
    session: Session = Session.objects.get_or_fetch(payment_case.session_number)
    context: dict[str, Any] = {"link": link, "session": Session}

    send_notification(
        subject="[Protection Civile] Inscription avec le Pass Région",
        from_email=org.email,
        to=payment_case.user.email,
        text_template="main/mail/authentication_link.html",
        html_template="main/mail/authentication_link.html",
        context=context,
    )


def send_payment_case_confirmation_notification():
    """Send a notification to the customer when the complete payment is confirmed"""


def send_pass_region_registration_notification():
    """Send a notification to the managers when a customer registered a new Pass Region credentials"""
    ...


def send_credit_card_payment_confirmation_notification():
    """Send a notification to the managers when we received payment confirmation for a credit card payment"""
    ...


def send_notification(
    subject: str,
    from_email: str,
    to: str,
    text_template: str,
    html_template: str,
    context: dict[str, Any],
):
    text_content = render_to_string(text_template, context)
    html_content = render_to_string(html_template, context)

    technical_from = settings.DEFAULT_FROM_EMAIL

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=technical_from,
        reply_to=[from_email],
        to=[to],
    )
    email.attach_alternative(html_content, "text/html")
    email.send()
