from django.db import models
from django.core import validators
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.conf import settings

from main.fields import EncryptedCharField


class PaymentCase(models.Model):
    class Meta:
        verbose_name = _("Dossier de paiement")
        verbose_name_plural = _("Dossiers de paiement")

    user = models.OneToOneField(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_number = models.fields.CharField(
        _("Numéro de la session"), validators=[validators.RegexValidator(r"\d*")]
    )
    total_payments_required = models.fields.IntegerField(
        _("Nombre de paiements Pass Région requis"), default=1
    )
    completed = models.fields.BooleanField(_("Paiement complet"), default=False)
    passregionpayment_set: models.QuerySet["PassRegionPayment"]

    def total_amount_required(self):
        return self.total_payments_required * 30


class CardPayment(models.Model):
    class CardPaymentChoice(models.TextChoices):
        WAITING_PAYMENT = "WP", _("En attente de paiement")
        PAYMENT_SUCCESS = "PS", _("Paiement réussi")
        PAYMENT_CONFIRMED = "PC", _("Paiement confirmé")
        PAYMENT_FAILED = "PF", _("Paiement échoué")

    class Meta:
        verbose_name = _("Paiement CB")
        verbose_name_plural = _("Paiements CB")
        indexes = [models.Index(fields=["checkout_intent_id"])]

    checkout_intent_id = models.fields.CharField(unique=True)
    redirect_url = models.fields.URLField()
    redirect_url_expires_at = models.DateTimeField()
    payment_status = models.fields.CharField(
        choices=CardPaymentChoice, default=CardPaymentChoice.WAITING_PAYMENT
    )
    payment_case = models.ForeignKey(to=PaymentCase, on_delete=models.CASCADE)


class PassRegionPayment(models.Model):
    class PassRegionPaymentChoice(models.TextChoices):
        WAITING_CREDENTIALS = "WC", _l(
            "En attente des identifiants Pass Région"
        )
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

    payment_status = models.fields.CharField(choices=PassRegionPaymentChoice, default=PassRegionPaymentChoice.WAITING_PAYMENT)
    payment_date = models.fields.DateField(_("Date de paiement"), null=True, blank=True)
    payment_case = models.ForeignKey(to=PaymentCase, on_delete=models.CASCADE)

    comment = models.fields.TextField(_("Commentaire"), null=True, blank=True)

    @property
    def fullname(self) -> str:
        return f"{self.holder_firstname.capitalize()} {self.holder_lastname.upper()}"

    def save(self, *args, **kwargs):
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
