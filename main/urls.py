from django.urls import path
from django.contrib import admin

import main.views as views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('payments/<int:pk>', views.PaymentCaseDetail.as_view(), name="payment-case"),
    path('payments/<int:pk>/pass-region', views.PassRegionPaymentCreate.as_view(), name="pass-region-payment")
]
