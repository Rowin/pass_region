from probatio import (
    REMOVE_EXTRA,
    All,
    Any,
    Length,
    Match,
    Optional,
    Range,
    Required,
    Schema,
)

TOKEN_RESPONSE_SCHEMA = Schema(
    {
        Required("access_token"): All(str, Length(min=1)),
        Required("refresh_token"): All(str, Length(min=1)),
        Optional("token_type"): "bearer",
        Required("expires_in"): Any(int, All(str, Match(r"\A0*[1-9][0-9]*\Z"))),
    },
)
"""Validate token responses; expires_in remains a positive seconds string.

Tokens and expiration are required by the client even though the reference
does not mark them as required. Undocumented response fields are rejected.
"""

CHECKOUT_INTENT_RESPONSE_SCHEMA = Schema(
    {
        Required("id"): All(int, Range(min=1, max=2147483647)),
        Required("redirectUrl"): All(str, Length(min=1)),
    },
)
"""Validate checkout creation responses with a positive int32 ID.

The client requires both fields and a non-empty redirectUrl, although the
reference allows omitted fields and a null redirectUrl. Extra fields are rejected.
"""

WEBHOOK_REQUEST_SCHEMA = Schema(
    {
        Required("eventType"): "Order",
        Required("data"): {
            Required("checkoutIntentId"): int,
            Required("payments"): All(Length(min=1, max=1), [{Required("state"): str}]),
        },
    },
    extra=REMOVE_EXTRA,
)
