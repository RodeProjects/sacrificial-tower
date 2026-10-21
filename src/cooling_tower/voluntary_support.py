"""Prepare a one-off PayPal contribution without network access or persistence."""
from __future__ import annotations

from decimal import Decimal
import re
from urllib.parse import urlencode


SUPPORT_PRESETS = ("3.50", "5.00", "10.00", "15.00", "20.00")
SUPPORT_AMOUNT_MIN = Decimal("2.50")
SUPPORT_AMOUNT_MAX = Decimal("50.00")
SUPPORT_AMOUNT_RANGE_TEXT = f"{SUPPORT_AMOUNT_MIN:.2f} bis {SUPPORT_AMOUNT_MAX:.2f} €".replace(".", ",")
SUPPORT_AMOUNT_PATTERN = r"[0-9]{1,4}(?:[.,][0-9]{1,2})?"
PAYPAL_PRIVACY_URL = "https://www.paypal.com/de/legalhub/paypal/privacy-full"


def parse_support_amount(text: str) -> Decimal:
    """Accept unambiguous EUR amounts; never round or interpret grouping marks."""
    value = text.strip()
    if not re.fullmatch(SUPPORT_AMOUNT_PATTERN, value):
        raise ValueError(f"Bitte einen Betrag von {SUPPORT_AMOUNT_RANGE_TEXT} mit höchstens zwei Nachkommastellen eingeben.")
    amount = Decimal(value.replace(",", "."))
    if not SUPPORT_AMOUNT_MIN <= amount <= SUPPORT_AMOUNT_MAX:
        raise ValueError(f"Bitte einen Betrag von {SUPPORT_AMOUNT_RANGE_TEXT} eingeben.")
    return amount


def validate_support_recipient(recipient: str) -> None:
    if not re.fullmatch(r"[^@\s<>\[\]]+@[^@\s<>\[\]]+\.[a-zA-Z]{2,}", recipient):
        raise ValueError("Die PayPal-Empfängeradresse ist nicht gültig hinterlegt.")


def paypal_support_url(amount_text: str, recipient: str) -> str:
    """Use PayPal's documented Payments Standard donation parameters.

    This is a browser handoff, never a payment confirmation. No payer data,
    application state, callback, subscription or tracking identifier is added.
    """
    amount = parse_support_amount(amount_text)
    validate_support_recipient(recipient)
    query = urlencode({
        "cmd": "_donations",
        "business": recipient,
        "item_name": "Sacrificial Tower - freiwillige Unterstützung ohne Gegenleistung",
        "amount": format(amount, ".2f"),
        "currency_code": "EUR",
        "no_shipping": "1",
        "charset": "utf-8",
        "lc": "DE",
    })
    return f"https://www.paypal.com/cgi-bin/webscr?{query}"
