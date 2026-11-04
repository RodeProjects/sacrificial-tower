"""Fit uniform numeric fields to their current text, units and spin controls."""
from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox


def fit_numeric_fields(rows):
    rows = tuple(rows)
    if not rows:
        return
    for row in rows:
        row.unit_label.ensurePolished()
    previous_unit_width = max(row.unit_label.fontMetrics().horizontalAdvance(row.unit_label.text())+4
        for row in rows)
    unit_width = max(previous_unit_width, *(row.unit_label.minimumSizeHint().width()
        for row in rows))
    # The label's style padding and glyph bearings need real space too.
    # Take it equally from both value gaps, retaining the existing box budget.
    extra = unit_width-previous_unit_width
    reduction = min(4, (extra+1)//2)
    left_gap, right_gap = 8-reduction, 4-reduction
    width_budget = max(0, 2*reduction-extra)
    required = []
    for row in rows:
        spin = row.editor
        spin.ensurePolished()
        # The spinbox already reserves value/unit padding. A second QLineEdit
        # padding from the application theme would clip the measured text.
        input_style = "QLineEdit { min-height: 0; padding: 0; border: 0; background: transparent; }"
        if spin.lineEdit().styleSheet() != input_style:
            spin.lineEdit().setStyleSheet(input_style)
        row.unit_label.setFixedWidth(unit_width)
        padding = f"QDoubleSpinBox, QSpinBox {{ padding: 0 {unit_width+right_gap}px 0 {left_gap}px; }}"
        if spin.styleSheet() != padding:
            spin.setStyleSheet(padding)
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        field = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,
            option, QStyle.SubControl.SC_SpinBoxEditField, spin)
        margins = spin.lineEdit().textMargins()
        text = spin.lineEdit().text() or "0"
        metrics = spin.lineEdit().fontMetrics()
        text_width = max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width())
        required.append(text_width+margins.left()+margins.right()+4+spin.width()-field.width()+width_budget)
    width = max(required)
    for row in rows:
        row.editor.setFixedWidth(width)
        row.range_label.setFixedWidth(width+30)
        row._position_unit_label()
