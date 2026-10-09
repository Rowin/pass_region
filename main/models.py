from django.db import models
from django.core import validators
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from main.fields import EncryptedCharField

class PaymentCase(models.Model):
    class Meta:
        verbose_name = _("Dossier de paiement")
        verbose_name_plural = _("Dossiers de paiement")

    firstname = models.fields.CharField(_("Prénom"))
    lastname = models.fields.CharField(_("Nom"))
    email = models.fields.EmailField(_("Adresse e-mail"))
    session_number = models.fields.CharField(_("Numéro de la session"), validators=[validators.RegexValidator(r"\d*")])
    required_pass_region = models.fields.IntegerField(_("Nombre de paiements Pass Région requis"), default=1)
    
class CardPayment(models.Model):
    class CardPaymentChoice(models.TextChoices):
        YES = "YES", "YES"

    class Meta:
        verbose_name = _("Paiement CB")
        verbose_name_plural = _("Paiements CB")
    
    checkout_intent_id = models.fields.CharField(validators=[validators.RegexValidator(r"\d*")])
    payment_status = models.fields.CharField(choices=CardPaymentChoice)
    payment_case = models.ForeignKey(to=PaymentCase, on_delete=models.CASCADE)

class PassRegionPayment(models.Model):
    class PassRegionPaymentChoice(models.TextChoices):
        WAITING_CREDENTIALS = "WAITING_CREDENTIALS", _l("En attente des identifiants Pass Région")
        WAITING_PAYMENT = "WAITING_PAYMENT", _l("En attente de prélèvement")
        PAYMENT_REJECTED = "PAYMENT_REJECTED", _l("Prélèvement rejeté")
        PAYMENT_APPROVED = "PAYMENT_APPROVED", _l("Prélèvement accepté")

    class Meta:
        verbose_name = _("Paiement Pass Région")
        verbose_name_plural = _("Paiements Pass Région")

    holder_firstname = models.fields.CharField(_("Prénom du titulaire"))
    holder_lastname = models.fields.CharField(_("Nom du titulaire"))
    card_number = models.fields.CharField(_("Numéro de carte"), validators=[validators.RegexValidator(r"\d*")])
    card_pin = EncryptedCharField(_("Code PIN"), max_length=200, null=True, blank=True)

    payment_status = models.fields.CharField(choices=PassRegionPaymentChoice)
    payment_date = models.fields.DateField(_("Date de paiement"), null=True, blank=True)
    payment_case = models.ForeignKey(to=PaymentCase, on_delete=models.CASCADE)

    comment = models.fields.TextField(_("Commentaire"), null=True, blank=True)

    @property
    def fullname(self) -> str:
        return f'{self.holder_firstname.capitalize()} {self.holder_lastname.upper()}'

    def save(self, *args, **kwargs):
        if self.payment_status in (self.PassRegionPaymentChoice.PAYMENT_APPROVED, self.PassRegionPaymentChoice.PAYMENT_REJECTED):
            self.card_pin = None

        super().save(*args, **kwargs)
    

class APICredentialRecord(models.Model):
    refresh_token = EncryptedCharField()
    access_token = EncryptedCharField()
    access_token_expires_at = models.DateTimeField()
    