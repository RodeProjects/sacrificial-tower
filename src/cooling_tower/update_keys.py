from __future__ import annotations


CURRENT_UPDATE_SIGNING_KEY_ID = "2026-10-private-publisher"

# Public verification keys are safe to ship with the application. The matching
# private key is protected by Windows DPAPI in the developer publishing account.
# It is never supplied to CI tests or builds.
UPDATE_MANIFEST_PUBLIC_KEYS = {
    CURRENT_UPDATE_SIGNING_KEY_ID: (
        "EDvSXoPRf/lJ45hc5wp+G6qldONsud6TPKNcR+vdQZ4="
    ),
}
