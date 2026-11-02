"""Native-specific style snapshots; STL method styles are not modified."""

EDITOR_STYLE = '''
QWidget#nativeProjectEditor QDoubleSpinBox:disabled, QWidget#nativeProjectEditor QSpinBox:disabled {
    color: #74808c; background: #edf0f2; border-color: #d6dde3;
}
QWidget#nativeProjectEditor QDoubleSpinBox::up-button:disabled,
QWidget#nativeProjectEditor QDoubleSpinBox::down-button:disabled {
    background: #e4e9ed; border-color: #d6dde3;
}
QWidget#nativeProjectEditor QLabel#numericEditorUnit:disabled { color: #8995a0; }
'''

FOOTER_STYLE = '''
QWidget#nativeProjectFooter { background: #f3f6f9; border-top: 1px solid #cbd6e1; }
QWidget#nativeProjectFooter QPushButton { min-height: 30px; max-height: 30px; padding: 0 12px; }
QWidget#nativeProjectFooter QWidget#footerActionArea QPushButton {
    min-height: 34px; max-height: 34px; padding: 7px 13px;
}
QWidget#nativeProjectFooter QPushButton#nativeCancelButton {
    color: #8c2820; background: #f8e4e4; border: 1px solid #dfbcbc;
}
QWidget#nativeProjectFooter QPushButton#nativeCancelButton:hover { background: #eac5c5; }
'''

NATIVE_DROP_STYLE = 'QWidget#preparationStepPage[stepTone="source"] QFrame#nativeProjectDropZone[completed="true"] {\n    background: #f6fafd;\n    border-color: #2f6690;\n}\nQFrame#nativeProjectDropZone {\n    background: #f6fafd;\n    border: 2px dashed #2f6690;\n    border-radius: 10px;\n    /* 180 px Inhaltsminimum + Rahmen ergeben dieselben 184 px wie die\n       frühere leere Darstellung mit den inzwischen ausgeblendeten Zeilen. */\n    min-height: 256px;\n}\nQFrame#nativeProjectDropZone[loaded="true"] {\n    min-height: 96px;\n    background: #f6fafd;\n    border: 2px dashed #2f6690;\n}\nQFrame#nativeProjectDropZone[completed="true"] {\n    background: #f6fafd;\n    border-color: #2f6690;\n}\nQFrame#nativeProjectDropZone[dragActive="true"] {\n    background: #deeff8;\n    border-color: #15527f;\n    border-style: solid;\n}\nQWidget#preparationStepPage[stepTone="source"]\nQFrame#nativeProjectDropZone[dragActive="true"] {\n    background: #deeff8;\n    border-color: #15527f;\n    border-style: solid;\n}\nQFrame#nativeProjectDropZone QLabel[replacementHint="true"] {\n    color: #6f7d89;\n    font-style: italic;\n    font-size: 9.3pt;\n    padding: 3px 0 5px 0;\n}\nQFrame#nativeProjectDropZone QLabel#sourceInfoCaption {\n    color: #647586;\n    font-weight: 600;\n    min-width: 82px;\n}\nQFrame#nativeProjectDropZone QLabel#sourceFilePath { color: #43576a; }\nQFrame#nativeProjectDropZone QLabel#dropFileName { font-weight: 650; color: #21384f; }\nQFrame#nativeProjectDropZone QPushButton#sourcePrimaryActionButton {\n    color: #28563d;\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #e7f8ed, stop: 1 #c7e9d3);\n    border-color: #a6cbb4;\n    font-size: 10pt;\n    font-weight: 650;\n}\nQFrame#nativeProjectDropZone QPushButton#sourcePrimaryActionButton:hover {\n    color: #214b35;\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #effbf3, stop: 1 #d3efdc);\n    border-color: #86b798;\n}\nQFrame#nativeProjectDropZone QPushButton#sourcePrimaryActionButton {\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #e7f8ed, stop: 1 #c7e9d3);\n}\nQFrame#nativeProjectDropZone QPushButton#sourcePrimaryActionButton:hover {\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #effbf3, stop: 1 #d3efdc);\n}\nQFrame#nativeProjectDropZone QPushButton#sourcePrimaryActionButton:pressed {\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #bddfc9, stop: 1 #e2f6e9);\n}\nQFrame#nativeProjectDropZone QPushButton#sourcePrimaryActionButton:disabled {\n    color: #7994aa;\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #f6f9fa, stop: 1 #e7edf1);\n    border-color: #d3dde5;\n}\nQFrame#nativeProjectDropZone QPushButton#removeSourceButton {\n    color: #7d4141;\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #faeeee, stop: 1 #f2dada);\n    border-color: #dfbcbc;\n    font-weight: 600;\n}\nQFrame#nativeProjectDropZone QPushButton#removeSourceButton:hover {\n    color: #713636;\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #f8e4e4, stop: 1 #eac5c5);\n    border-color: #cc9d9d;\n}\nQFrame#nativeProjectDropZone QPushButton#removeSourceButton:pressed {\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #eacaca, stop: 1 #f6e7e7);\n}\nQFrame#nativeProjectDropZone QPushButton#removeSourceButton:disabled {\n    color: #8995a0;\n    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,\n        stop: 0 #f5f7f8, stop: 1 #e7ecef);\n    border-color: #d8dee3;\n}'
