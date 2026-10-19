"""Orca settings for explicitly requested source-object support simulation."""


def simulated_support_settings() -> dict[str, str]:
    return {
        "enable_support": "1",
        "support_type": "tree(auto)",
        # Let Orca choose its compatible tree style, rather than retaining a
        # normal-support-only style from a profile with supports switched off.
        "support_style": "default",
        "independent_support_layer_height": "0",
    }
