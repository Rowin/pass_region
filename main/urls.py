from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path
from django.urls.resolvers import URLPattern, URLResolver
from sesame.views import LoginView

import main.views as views

urlpatterns: list[URLResolver | URLPattern] = [
    path("admin/", admin.site.urls),
    path("me/payments/", views.PaymentCaseDetail.as_view(), name="payment-case"),
    path(
        "pass-region",
        views.PassRegionPaymentCreate.as_view(),
        name="pass-region-payment",
    ),
    path("card-payment", views.CardPaymenRedirect.as_view(), name="card-payment"),
    path(
        "card-payment/return/<str:callback_type>",
        views.CardPaymentCallback.as_view(),
        name="card-payment-return",
    ),
    path("hook/<uuid:org_uuid>", views.HelloAssoWebhook.as_view(), name="webhook"),
    path("login/auth/", LoginView.as_view(next_page="payment-case"), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
