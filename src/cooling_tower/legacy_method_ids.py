"""Read-only identifiers for earlier settings, output folders and G-code."""

LEGACY_POSTPROCESSOR_ID = "preprocessor"
LEGACY_POSTPROCESSOR_EXPORT_SETTING = f"export_roots.{LEGACY_POSTPROCESSOR_ID}"
LEGACY_POSTPROCESSOR_BEGIN = f"; SACRIFICIAL_TOWER_{LEGACY_POSTPROCESSOR_ID.upper()}_BEGIN"
