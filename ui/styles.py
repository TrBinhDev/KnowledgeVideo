STYLESHEET = """
* { font-family: "Segoe UI"; font-size: 9.5pt; color: #1e293b; }
QMainWindow, QWidget#app { background: #f5f7fb; }
QScrollArea, QWidget#page { background: transparent; border: none; }
QLabel { background: transparent; }

/* sidebar */
QFrame#sidebar { background: #ffffff; border-right: 1px solid #e5e9f2; }
QLabel#brand { font-size: 13pt; font-weight: 700; color: #0f172a; }
QLabel#brandSub { color: #64748b; font-size: 8pt; }
QLabel#navSection { color: #94a3b8; font-size: 7.5pt; font-weight: 600; padding: 12px 10px 4px 10px; }
QPushButton#navItem { text-align: left; border: none; border-radius: 8px; padding: 8px 10px; background: transparent; color: #334155; }
QPushButton#navItem:hover { background: #f1f5f9; }
QPushButton#navItem:checked { background: #eef3ff; color: #1d4ed8; font-weight: 600; }
QPushButton#navItem:disabled { color: #94a3b8; }
QFrame#storage { background: #f8fafc; border: 1px solid #e5e9f2; border-radius: 10px; }
QLabel#storageText { color: #64748b; font-size: 8pt; }

/* page header and step bar */
QLabel#pageTitle { font-size: 17pt; font-weight: 700; color: #0f172a; }
QLabel#pageSubtitle { color: #64748b; }
QFrame#stepBar { background: #ffffff; border: 1px solid #e5e9f2; border-radius: 12px; }
QLabel#stepCircle { border-radius: 14px; background: #eef2f7; color: #64748b; font-weight: 600; }
QLabel#stepCircle[state="current"] { background: #2563eb; color: white; }
QLabel#stepCircle[state="done"] { background: #dbeafe; color: #1d4ed8; }
QLabel#stepTitle { font-weight: 600; color: #475569; }
QLabel#stepTitle[state="current"] { color: #1d4ed8; }
QLabel#stepTitle[state="todo"] { color: #94a3b8; }
QLabel#stepSubtitle { color: #94a3b8; font-size: 8pt; }
QFrame#stepLine { background: #e2e8f0; border: none; }

/* cards */
QFrame#card { background: #ffffff; border: 1px solid #e5e9f2; border-radius: 14px; }
QLabel#badge { background: #2563eb; border-radius: 15px; }
QLabel#cardTitle { font-size: 11.5pt; font-weight: 600; color: #0f172a; }
QLabel#cardSubtitle, QLabel#hint { color: #64748b; font-size: 8.5pt; }
QLabel#fieldLabel { color: #475569; font-size: 8.5pt; font-weight: 600; }
QLabel#counter { color: #94a3b8; font-size: 8pt; }
QLabel#preview { background: #eef2f7; border: 1px solid #e2e8f0; border-radius: 10px; color: #94a3b8; }
QFrame#panel { background: #f8fafc; border: 1px solid #e5e9f2; border-radius: 10px; }
QLabel#panelTitle { font-weight: 600; color: #0f172a; }
QLabel#specKey { color: #64748b; }
QLabel#specValue { color: #0f172a; font-weight: 600; }
QLabel#okTag { background: #dcfce7; color: #15803d; border-radius: 6px; padding: 2px 8px; font-size: 8pt; font-weight: 600; }
QLabel#outlineView, QLabel#scriptView { background: #f8fafc; border: 1px solid #e5e9f2; border-radius: 10px; padding: 12px; }

/* selectable cards */
QFrame#choice { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; }
QFrame#choice:hover { border-color: #93b4f8; }
QFrame#choice[selected="true"] { border: 2px solid #2563eb; background: #f5f8ff; }
QFrame#choice:disabled { background: #f8fafc; border-color: #e2e8f0; }
QLabel#choiceArt { background: #eef3ff; border-radius: 8px; }
QLabel#choiceIcon { background: #eef3ff; border-radius: 8px; }
QLabel#choiceTitle { font-weight: 600; color: #0f172a; }
QLabel#choiceTitle:disabled { color: #94a3b8; }
QLabel#choiceSubtitle { color: #64748b; font-size: 8.5pt; }
QLabel#choiceBadge { background: #f1f5f9; color: #64748b; border-radius: 6px; padding: 1px 6px; font-size: 7.5pt; }

/* inputs and buttons */
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {
    background: #ffffff; border: 1px solid #dbe2ec; border-radius: 8px; padding: 6px 8px;
    selection-background-color: #bfdbfe; selection-color: #0f172a;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #2563eb; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #dbe2ec; selection-background-color: #eef3ff; selection-color: #1d4ed8; }
QListWidget::item { padding: 8px; border-radius: 8px; }
QListWidget::item:selected { background: #eef3ff; color: #1e3a8a; }
QPushButton { background: #ffffff; border: 1px solid #dbe2ec; border-radius: 8px; padding: 7px 14px; color: #1e293b; }
QPushButton:hover { background: #f1f5f9; }
QPushButton#primary { background: #2563eb; color: white; border: none; font-weight: 600; padding: 9px 18px; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#link { border: none; background: transparent; color: #2563eb; padding: 2px 4px; font-weight: 600; }
QPushButton#link:hover { color: #1d4ed8; }
QPushButton#tab { background: transparent; border: 1px solid transparent; color: #475569; padding: 7px 14px; }
QPushButton#tab:hover { background: #f1f5f9; }
QPushButton#tab:checked { background: #eef3ff; border-color: #d6e2ff; color: #1d4ed8; }
QPushButton#soft { background: #eef3ff; border: 1px solid #d6e2ff; color: #1d4ed8; }
QPushButton#soft:hover { background: #e0eaff; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0; }
QCheckBox { spacing: 8px; }

/* flow banner at the top of step 1: blue for the picture flow, amber for the clip flow */
QFrame#flowBanner { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 12px; }
QFrame#flowBanner[kind="clip"] { background: #fff7ed; border-color: #fdba74; }
QLabel#flowIcon { background: #2563eb; border-radius: 18px; }
QLabel#flowIcon[kind="clip"] { background: #ea580c; }
QLabel#flowTitle { font-weight: 700; font-size: 10.5pt; color: #1d4ed8; }
QLabel#flowTitle[kind="clip"] { color: #c2410c; }
QLabel#flowText { color: #475569; font-size: 8.5pt; }
QFrame#clipLinkBox { background: #fff7ed; border: 1px dashed #fdba74; border-radius: 10px; }

/* call to action bars */
QFrame#ctaBar { background: #f5f8ff; border: 1px solid #d6e2ff; border-radius: 12px; }
QFrame#doneBar { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; }
QLabel#ctaTitle { font-weight: 600; color: #0f172a; }

/* dark render panel */
QFrame#renderPanel { background: #0f172a; border-radius: 14px; }
QLabel#renderTitle { color: #ffffff; font-weight: 600; font-size: 11pt; }
QLabel#renderDetail { color: #94a3b8; font-size: 8.5pt; }
QLabel#renderPercent { color: #60a5fa; font-size: 20pt; font-weight: 700; }
QProgressBar#renderBar { background: #1e293b; border: none; border-radius: 4px; max-height: 8px; }
QProgressBar#renderBar::chunk { border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #22c55e); }
QFrame#renderStage { background: #1e293b; border: 1px solid #334155; border-radius: 10px; }
QFrame#renderStage[state="active"] { border-color: #3b82f6; }
QLabel#renderMark { border-radius: 12px; background: #334155; color: #cbd5e1; font-weight: 700; }
QLabel#renderMark[state="active"] { background: #2563eb; color: white; }
QLabel#renderMark[state="done"] { background: #22c55e; color: white; }
QLabel#renderMark[state="failed"] { background: #ef4444; color: white; }
QLabel#renderStageName { color: #e2e8f0; font-weight: 600; font-size: 8.5pt; }
QLabel#renderStageState { color: #94a3b8; font-size: 8pt; }
QPushButton#darkButton { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; }
QPushButton#darkButton:hover { background: #334155; }
QPushButton#darkButton:disabled { color: #64748b; background: #1e293b; }

/* bottom status bar */
QFrame#statusBar { background: #ffffff; border-top: 1px solid #e5e9f2; }
QLabel#status { color: #475569; }
QProgressBar#thinBar { background: #e2e8f0; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar#thinBar::chunk { background: #2563eb; border-radius: 3px; }
QListWidget#timeline { font-family: "Consolas"; font-size: 8.5pt; color: #334155; background: #f8fafc; }

/* scroll bars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:horizontal { background: #cbd5e1; border-radius: 3px; min-width: 30px; }
QScrollBar::handle:hover { background: #94a3b8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
