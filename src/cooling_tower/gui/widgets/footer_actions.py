"""Shared label fitting and action placement for generation footers."""
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget


def fit_footer_actions(
    layout: QGridLayout,
    folder_buttons: tuple[QWidget, QWidget, QWidget],
    action_buttons: tuple[QWidget, ...],
    inner_width: int,
    set_labels: Callable[[bool, int, bool], None],
) -> tuple[bool, str]:
    """Fit two columns first, then stack and wrap using the same label stages."""
    spacing = layout.horizontalSpacing()
    report_visible = not folder_buttons[2].isHidden()

    def width(button):
        return max(button.sizeHint().width(), button.minimumWidth())

    def required_width():
        visible = [button for button in (*folder_buttons, *action_buttons) if not button.isHidden()]
        return (sum(width(button) for button in visible)
            + spacing * max(0, len(visible)-1)
            + (2*spacing if any(not button.isHidden() for button in action_buttons)
                and any(not button.isHidden() for button in folder_buttons) else 0)
            + (spacing+2 if visible else 0))

    for narrow, available in ((False, max(0, (inner_width-13)//2)), (True, inner_width)):
        stages = [(False, 0, False)]
        if report_visible:
            stages.extend(((False, 1, False), (False, 2, False)))
        stages.extend(((True, 2 if report_visible else 0, False),
            (True, 2 if report_visible else 0, True)))
        for stage in stages:
            set_labels(*stage)
            if required_width() <= available:
                break
        if required_width() <= available:
            break

    primary = [button for button in action_buttons if not button.isHidden()]
    primary_width = sum(width(button) for button in primary)+spacing*max(0, len(primary)-1)
    paired_width = sum(width(button) for button in folder_buttons[:2] if not button.isHidden())
    paired_width += primary_width+spacing*5+2
    mode = ("single" if required_width() <= available else
        "report_above" if report_visible and paired_width <= available else
        "report_and_action_above" if report_visible else "action_below")
    if mode != getattr(layout, "_footer_actions_mode", None):
        layout._footer_actions_mode = mode
        widgets = (*folder_buttons, *action_buttons)
        hidden = {widget: widget.isHidden() for widget in widgets}
        for widget in widgets:
            layout.removeWidget(widget)
        report_above = mode in {"report_above", "report_and_action_above"}
        folder_row = 1 if report_above else 0
        layout.setVerticalSpacing(8 if mode != "single" else 0)
        for column, button in enumerate(folder_buttons[:2]):
            layout.addWidget(button, folder_row, column, Qt.AlignmentFlag.AlignBottom)
        if report_above:
            layout.addWidget(folder_buttons[2], 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        else:
            layout.addWidget(folder_buttons[2], 0, 2, Qt.AlignmentFlag.AlignBottom)
        below = mode in {"action_below", "report_and_action_above"}
        for index, button in enumerate(action_buttons):
            if below and index == 0:
                layout.addWidget(button, folder_row+1, 0, 1, 5, Qt.AlignmentFlag.AlignRight)
            elif below:
                layout.addWidget(button, folder_row+1, 4+index, Qt.AlignmentFlag.AlignRight)
            else:
                layout.addWidget(button, folder_row, 4+index, Qt.AlignmentFlag.AlignBottom)
        layout.invalidate()
        for widget, was_hidden in hidden.items():
            widget.setVisible(not was_hidden)
    return narrow, mode
