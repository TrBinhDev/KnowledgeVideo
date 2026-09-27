STYLESHEET = """
QWidget { font-family: "Segoe UI"; font-size: 10pt; color: #1f2937; background: #f8fafc; }
QLabel#heading { font-size: 16pt; font-weight: 600; margin-bottom: 4px; }
QLabel#hint { color: #64748b; }
QLabel#status { color: #475569; padding: 6px 2px; }
QLabel#preview { background: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 6px; }
QListWidget#steps { background: #0f172a; color: #cbd5e1; border: none; padding: 8px; font-size: 11pt; }
QListWidget#steps::item { padding: 10px 8px; border-radius: 6px; }
QListWidget#steps::item:selected { background: #2563eb; color: white; }
QListWidget#steps::item:disabled { color: #475569; }
QListWidget, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px;
}
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: #dbeafe; color: #1e3a8a; }
QPushButton { background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #f1f5f9; }
QPushButton#primary { background: #2563eb; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; }
QListWidget#timeline { font-family: "Consolas"; font-size: 9pt; color: #334155; }
QProgressBar { border: 1px solid #cbd5e1; border-radius: 6px; text-align: center; background: white; height: 18px; }
QProgressBar::chunk { background: #2563eb; border-radius: 6px; }
"""
