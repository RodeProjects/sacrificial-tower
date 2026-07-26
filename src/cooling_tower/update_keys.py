from __future__ import annotations


CURRENT_UPDATE_SIGNING_KEY_ID = "2026-07-primary"

# Public verification keys are safe to ship with the application. The matching
# private key exists only as an encrypted GitHub Actions repository secret.
UPDATE_MANIFEST_PUBLIC_KEYS = {
    CURRENT_UPDATE_SIGNING_KEY_ID: (
        "1Bhua5nXf1fTwOR1vh6FKRe1vKHDGjHcrNDs0ZOCl2g="
    ),
}
