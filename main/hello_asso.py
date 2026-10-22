from decimal import Decimal
from typing import Any, cast

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.timezone import timedelta
from django.utils.translation import gettext as _

from main.models import APICredentialRecord


class HelloAssoAPI:
    """Minimal client for Hello Asso authentication and the Checkout API.

    Credentials and the organization slug are read from Django settings.
    Authentication tokens are stored in ``APICredentialRecord``.
    """

    AUTH_URL = "https://api.helloasso.com/oauth2/token"
    API_URL = "https://api.helloasso.com/v5"
    TOKEN_REFRESH_THRESHOLD = timedelta(minutes=2)

    def _request_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a POST request and decode its JSON object response.

        Args:
            url: Hello Asso endpoint URL.
            headers: HTTP request headers.
            data: Form-encoded request fields, if applicable.
            json_data: JSON request body, if applicable.

        Returns:
            The response JSON, expected to be an object.

        Raises:
            requests.HTTPError: If the server returns an error status.
            requests.RequestException: If a transport error occurs.
            requests.JSONDecodeError: If the response body is not valid JSON.
            ValueError: If the decoded JSON is not an object.
        """
        response = requests.post(
            url,
            data=data,
            json=json_data,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        decoded = response.json()

        if not isinstance(decoded, dict):
            raise ValueError(_("Hello Asso a retourné une réponse JSON invalide."))
        payload = cast(dict[str, Any], decoded)
        return payload

    def _get_setting(self, name: str) -> str:
        """Return a required non-empty Django setting.

        Args:
            name: Name of the required setting.

        Returns:
            The configured setting value.

        Raises:
            ImproperlyConfigured: If the setting is missing or empty.
        """
        value = getattr(settings, name, None)
        if not value:
            raise ImproperlyConfigured(
                _(
                    "The Django setting %(setting_name)s must be configured."
                ) % {"setting_name": name}
            )
        return value

    def _token_response(self, credential: APICredentialRecord | None) -> dict[str, Any]:
        """Request token data using a refresh token or client credentials.

        If a credential record exists, its refresh token is used. Otherwise,
        client credentials are sent to obtain the initial tokens.

        Args:
            credential: Existing credential record to refresh, or ``None`` for
                the initial authentication.

        Returns:
            The fields from the authentication endpoint's JSON response.

        Raises:
            ImproperlyConfigured: If the initial client credentials are missing.
            requests.RequestException: If an HTTP or network error occurs.
            ValueError: If the response body is not a valid JSON object.
        """
        if credential is not None:
            return self._request_json(
                self.AUTH_URL,
                json_data={
                    "grant_type": "refresh_token",
                    "refresh_token": credential.refresh_token,
                },
                headers={"Content-Type": "application/json"},
            )

        return self._request_json(
            self.AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._get_setting("HELLO_ASSO_CLIENT_ID"),
                "client_secret": self._get_setting("HELLO_ASSO_CLIENT_SECRET"),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def _access_token(self) -> str:
        """Return a valid access token, refreshing it when necessary.

        A token with less remaining lifetime than the safety threshold is
        refreshed using the refresh token. Newly received tokens are saved to
        ``APICredentialRecord``.

        Returns:
            A Hello Asso access token.

        Raises:
            ImproperlyConfigured: If the initial client credentials are missing.
            requests.RequestException: If an HTTP or network error occurs.
            ValueError: If the authentication response is incomplete or invalid.
        """
        credential = APICredentialRecord.objects.order_by(
            "-access_token_expires_at"
        ).first()
        now = timezone.now()
        if (
            credential is not None
            and credential.access_token_expires_at > now + self.TOKEN_REFRESH_THRESHOLD
        ):
            return credential.access_token

        token_data = self._token_response(credential)
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError(_("La réponse Hello Asso ne contient pas d'access_token."))

        refresh_token = token_data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            if credential is None:
                raise ValueError(_("La réponse Hello Asso ne contient pas de refresh_token."))
            refresh_token = credential.refresh_token

        try:
            expires_in = int(token_data["expires_in"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                _(
                    "La réponse Hello Asso ne contient pas de durée de validité exploitable."
                )
            ) from error
        if expires_in <= 0:
            raise ValueError(
                _("La durée de validité du token Hello Asso doit être positive.")
            )

        expires_at = now + timedelta(seconds=expires_in)
        if credential is None:
            APICredentialRecord.objects.create(
                refresh_token=refresh_token,
                access_token=access_token,
                access_token_expires_at=expires_at,
            )
        else:
            credential.refresh_token = refresh_token
            credential.access_token = access_token
            credential.access_token_expires_at = expires_at
            credential.save(
                update_fields=[
                    "refresh_token",
                    "access_token",
                    "access_token_expires_at",
                ]
            )
        return access_token

    def create_checkout_intent(
        self,
        amount: Decimal | int | float,
        message: str,
        *,
        back_url: str,
        error_url: str,
        return_url: str,
        contains_donation: bool = False,
    ) -> str:
        """Create a Hello Asso Checkout and return its redirect URL.

        Args:
            amount: Amount in euros. It is converted to cents before the API
                request; fractions of a cent are rejected.
            message: Payment label sent as ``itemName`` (maximum 250 characters).
            back_url: URL the payer can use to return to the previous site.
            error_url: URL called if an error occurs during checkout.
            return_url: URL called after payment.
            contains_donation: Whether the payment includes a donation
                (defaults to ``False``).

        Returns:
            The ``redirectUrl`` returned by Hello Asso.

        Raises:
            ImproperlyConfigured: If the organization slug or the client
                credentials required for the initial token are not configured.
            ValueError: If the amount, message, or Hello Asso JSON response is
                invalid.
            requests.HTTPError: If Hello Asso returns an HTTP error status.
            requests.RequestException: If a network transport error occurs.
        """
        amount_in_cents = Decimal(str(amount)) * 100
        if amount_in_cents != amount_in_cents.to_integral_value():
            raise ValueError(
                _("Le montant ne peut pas contenir de fraction de centime.")
            )
        if not message or len(message) > 250:
            raise ValueError(_("Le message doit contenir entre 1 et 250 caractères."))

        organization_slug = self._get_setting("HELLO_ASSO_ORGANIZATION_SLUG")
        checkout_url = (
            f"{self.API_URL}/organizations/{organization_slug}/checkout-intents"
        )
        payload: dict[str, int | str | bool] = {
            "totalAmount": int(amount_in_cents),
            "initialAmount": int(amount_in_cents),
            "itemName": message,
            "backUrl": back_url,
            "errorUrl": error_url,
            "returnUrl": return_url,
            "containsDonation": contains_donation,
        }
        response = self._request_json(
            checkout_url,
            json_data=payload,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
        )
        redirect_url = response.get("redirectUrl")
        if not isinstance(redirect_url, str) or not redirect_url:
            raise ValueError(_("La réponse Hello Asso ne contient pas de redirectUrl."))
        return redirect_url
