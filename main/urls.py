from django.urls import path
from django.contrib import admin
from django.contrib.auth.views import LogoutView

from sesame.views import LoginView
from debug_toolbar.toolbar import debug_toolbar_urls

import main.views as views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('me/payments/', views.PaymentCaseDetail.as_view(), name="payment-case"),
    path('me/pass-region', views.PassRegionPaymentCreate.as_view(), name="pass-region-payment"),
    path('me/card-payment', views.CardPaymenRedirect.as_view(), name="card-payment"),
    path('login/auth/', LoginView.as_view(next_page="payment-case"), name="login"),
    path('logout/', LogoutView.as_view(), name="logout")
] + debug_toolbar_urls()
