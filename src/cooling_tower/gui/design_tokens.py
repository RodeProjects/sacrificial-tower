from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UiMetrics:
    """Shared geometry values for the desktop UI.

    Keeping these values in one place prevents individual screens from
    drifting apart while the remaining overhaul steps are implemented.
    """

    outer_gutter_px: int = 22
    content_gutter_px: int = 22
    card_spacing_px: int = 10
    card_radius_px: int = 10
    card_header_horizontal_padding_px: int = 16
    card_header_vertical_padding_px: int = 11
    card_header_summary_gap_px: int = 14
    card_header_height_px: int = 52
    card_badge_height_px: int = 24
    card_body_horizontal_padding_px: int = 10
    card_body_vertical_padding_px: int = 10
    form_row_vertical_padding_px: int = 1
    form_control_gap_px: int = 6
    form_editor_width_px: int = 150
    form_control_height_px: int = 36
    form_unit_width_px: int = 44
    form_spin_button_width_px: int = 24
    reset_button_size_px: int = 36
    info_button_diameter_px: int = 32
    prediction_value_padding_px: int = 5
    inline_hint_maximum_height_px: int = 118
    responsive_breakpoint_px: int = 1040
    animation_duration_ms: int = 0
    first_success_animation_duration_ms: int = 0


METRICS = UiMetrics()


COLORS: dict[str, str] = {
    "background": "#f3f6f9",
    "surface": "#ffffff",
    "surface_subtle": "#f7f9fc",
    "border": "#d6dee8",
    "text": "#152536",
    "text_secondary": "#526274",
    "primary": "#1769aa",
    "success": "#176b45",
    "success_surface": "#eaf7f0",
    "warning": "#8a4b08",
    "warning_surface": "#fff7e6",
    "error": "#b42318",
    "error_surface": "#fff1f0",
    "preview": "#6f52c9",
    "preview_surface": "#f3f0ff",
}
