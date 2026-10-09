from django.db import models
from django.contrib import admin

from main.models import PaymentCase, PassRegionPayment

class PassRegionInline(admin.TabularInline):
    model = PassRegionPayment
    fields = ["holder_firstname", "holder_lastname", "card_number", "card_pin", "payment_status", "payment_date"]
    readonly_fields = ["holder_firstname", "holder_lastname", "card_number", "card_pin", "payment_date"]
    max_num = 0

@admin.register(PaymentCase)
class PaymentCaseAdmin(admin.ModelAdmin):
    inlines = [PassRegionInline]

@admin.register(PassRegionPayment)
class PassRegionPaymentAdmin(admin.ModelAdmin):
    ...
