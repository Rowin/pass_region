import uuid
from typing import Any

from django.conf import settings
from django.core import validators
from django.db import models
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from main.fields import EncryptedCharField


class Organization(models.Model):
    class Meta:
        verbose_name = _("Organisation")

    organization_name = models.CharField(_("Nom de l'organisation"))

    hello_asso_client_id = EncryptedCharField(
        help_text=_("Client ID pour la connexion à l'API HelloAsso")
    )
    hello_asso_client_secret = EncryptedCharField(
        help_text=_("Client secret pour la connexion à l'API HelloAsso")
    )
    hello_asso_organization_slug = models.CharField(
        help_text=_("Slug de l'organisation pour la connexion à l'API HelloAsso")
    )

    copay_amount_per_candidate = models.DecimalField(
        _("Reste à charge par candidat (€)")
    )
    copay_message = models.CharField(
        _("Message à faire apparaitre pour le paiement"),
        help_text=_(
            "Ce message sera transmis à HelloAsso et apparaîtra comme nom de campagne"
        ),
    )

    webhook_uuid = models.UUIDField(default=uuid.uuid4(), unique=True)

    def __str__(self) -> str:
        return self.organization_name


class StaffUser(models.Model):
    class Meta:
        verbose_name = _("Gestionnaire")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ManyToManyField(
        to=Organization, verbose_name=_("Organisation")
    )


class PaymentCase(models.Model):
    class Meta:
        verbose_name = _("Dossier de paiement")
        verbose_name_plural = _("Dossiers de paiement")

    user = models.OneToOneField(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey(to=Organization, on_delete=models.CASCADE)
    session_number = models.fields.CharField(
        _("Numéro de la session"), validators=[validators.RegexValidator(r"\d*")]
    )
    total_payments_required = models.fields.IntegerField(
        _("Nombre de paiements Pass Région requis"), default=1
    )
    completed = models.fields.BooleanField(_("Paiement complet"), default=False)
    passregionpayment_set: models.QuerySet["PassRegionPayment"]

    def total_amount_required(self):
        return (
            self.total_payments_required * self.organization.copay_amount_per_candidate
        )


class CardPayment(models.Model):
    class CardPaymentChoice(models.TextChoices):
        WAITING_PAYMENT = "WP", _("En attente de paiement")
        WAITING_CONFIRMATION = "WC", _("En attente de confirmation du paiement")
        PAYMENT_CONFIRMED = "PC", _("Paiement confirmé")
        PAYMENT_FAILED = "PF", _("Paiement échoué")

    class Meta:
        verbose_name = _("Paiement CB")
        verbose_name_plural = _("Paiements CB")
        indexes = [models.Index(fields=["checkout_intent_id"])]

    checkout_intent_id = models.fields.CharField(unique=True)
    redirect_url = models.fields.URLField(max_length=500)
    redirect_url_expires_at = models.DateTimeField()
    payment_status = models.fields.CharField(
        _("Statut du paiement"),
        choices=CardPaymentChoice,
        default=CardPaymentChoice.WAITING_PAYMENT,
    )
    payment_confirmation_received_at = models.DateTimeField(
        _("Date de confirmation du paiement"), blank=True, null=True
    )
    payment_case = models.ForeignKey(
        to=PaymentCase, on_delete=models.CASCADE, verbose_name=_("Dossier de paiement")
    )


class PassRegionPayment(models.Model):
    class PassRegionPaymentChoice(models.TextChoices):
        WAITING_CREDENTIALS = "WC", _l("En attente des identifiants Pass Région")
        WAITING_PAYMENT = "WP", _l("En attente de prélèvement")
        PAYMENT_REJECTED = "PR", _l("Prélèvement rejeté")
        PAYMENT_APPROVED = "PA", _l("Prélèvement accepté")

    class Meta:
        verbose_name = _("Paiement Pass Région")
        verbose_name_plural = _("Paiements Pass Région")

    holder_firstname = models.fields.CharField(_("Prénom du titulaire"))
    holder_lastname = models.fields.CharField(_("Nom du titulaire"))
    card_number = models.fields.CharField(
        _("Numéro de carte"), validators=[validators.RegexValidator(r"\d*")]
    )
    card_pin = EncryptedCharField(_("Code PIN"), max_length=200, null=True, blank=True)

    payment_status = models.fields.CharField(
        choices=PassRegionPaymentChoice, default=PassRegionPaymentChoice.WAITING_PAYMENT
    )
    payment_date = models.fields.DateField(_("Date de paiement"), null=True, blank=True)
    payment_case = models.ForeignKey(to=PaymentCase, on_delete=models.CASCADE)

    comment = models.fields.TextField(_("Commentaire"), null=True, blank=True)

    @property
    def fullname(self) -> str:
        return f"{self.holder_firstname.capitalize()} {self.holder_lastname.upper()}"

    def save(self, *args: Any, **kwargs: Any):
        if self.payment_status in (
            self.PassRegionPaymentChoice.PAYMENT_APPROVED,
            self.PassRegionPaymentChoice.PAYMENT_REJECTED,
        ):
            self.card_pin = None

        super().save(*args, **kwargs)


class APICredentialRecord(models.Model):
    refresh_token = EncryptedCharField()
    access_token = EncryptedCharField()
    access_token_expires_at = models.DateTimeField()
    organization = models.ForeignKey(to=Organization, on_delete=models.CASCADE)
