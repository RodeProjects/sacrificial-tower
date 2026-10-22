"""Measure explicit result text lines independently of their current wrapping."""
from math import ceil

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel


def unwrapped_label_width(label, text_variants=()):
    label.ensurePolished()
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(label.font())
    widths = []
    for text in (label.text(), *text_variants):
        if label.textFormat() == Qt.TextFormat.RichText:
            document.setHtml(text)
        else:
            document.setPlainText(text)
        widths.append(ceil(document.idealWidth()))
    padding = label.contentsMargins()
    return max(widths) + padding.left() + padding.right()


def unwrapped_card_width(card, text_variants=None):
    """Include styled fonts and padding, reserving all supplied state variants."""
    card.ensurePolished()
    margins = card.layout().contentsMargins()
    frame = card.contentsMargins()
    variants = text_variants or {}
    widths = [unwrapped_label_width(label, variants.get(label, ()))
              for label in card.findChildren(QLabel)]
    return max(widths, default=0) + margins.left() + margins.right() + frame.left() + frame.right()
