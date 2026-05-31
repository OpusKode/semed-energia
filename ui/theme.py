"""
Tema visual inspirado no Claude: fundo escuro quente, tipografia limpa,
acento laranja (Anthropic) e bordas sutis.
"""

# ------------- Paleta -----------------
BG_APP       = "#1C1B1A"   # fundo principal
BG_SIDEBAR   = "#242321"   # sidebar
BG_CARD      = "#272624"   # cards / painéis
BG_HOVER     = "#302F2C"   # hover de botões/itens
BG_SELECTED  = "#3A3936"   # item selecionado
BORDER       = "#3A3937"   # bordas sutis
BORDER_STRONG= "#4A4845"

TEXT_PRIMARY   = "#ECE8E0" # texto principal (warm off-white)
TEXT_SECONDARY = "#9C9892"
TEXT_MUTED     = "#6E6B67"

ACCENT       = "#D97757"   # laranja Anthropic
ACCENT_HOVER = "#E4896D"
ACCENT_DIM   = "#8C4E39"

SUCCESS = "#7FAE6E"
WARNING = "#E0B060"
ERROR   = "#D46A6A"


STYLESHEET = f"""
* {{
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", -apple-system, sans-serif;
    font-size: 10pt;
}}

QMainWindow {{
    background-color: {BG_APP};
}}
QWidget#Page {{
    background: transparent;
}}

/* --- Sidebar --- */
QFrame#Sidebar {{
    background-color: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}
QLabel#SidebarTitle {{
    color: {ACCENT};
    font-size: 15px;
    font-weight: 600;
    padding: 18px 16px 8px 16px;
}}
QLabel#SidebarSubtitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
    padding: 0 16px 16px 16px;
}}
QPushButton#NavButton {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    text-align: left;
    padding: 9px 16px 9px 18px;
    border: none;
    border-left: 3px solid transparent;
    font-size: 13px;
}}
QPushButton#NavButton:hover {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton#NavButton:checked {{
    background-color: {BG_SELECTED};
    color: {TEXT_PRIMARY};
    border-left: 3px solid {ACCENT};
    font-weight: 600;
}}

/* --- Headings --- */
QLabel#PageTitle {{
    color: {TEXT_PRIMARY};
    font-size: 22px;
    font-weight: 600;
    padding: 0 0 4px 0;
}}
QLabel#PageSubtitle {{
    color: {TEXT_MUTED};
    font-size: 12px;
    padding: 0 0 20px 0;
}}
QLabel#SectionTitle {{
    color: {TEXT_PRIMARY};
    font-size: 14px;
    font-weight: 600;
    padding: 8px 0 6px 0;
}}

/* --- Cards --- */
QFrame#Card {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#CardValue {{
    font-size: 22px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#CardLabel {{
    font-size: 11px;
    color: {TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QLabel#CardAccent {{
    color: {ACCENT};
    font-size: 22px;
    font-weight: 600;
}}

/* --- Botões --- */
QPushButton {{
    background-color: {BG_HOVER};
    border: 1px solid {BORDER};
    padding: 7px 14px;
    border-radius: 7px;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {BG_SELECTED};
    border: 1px solid {BORDER_STRONG};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
}}
QPushButton#Primary {{
    background-color: {ACCENT};
    color: #1C1B1A;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background-color: {ACCENT_HOVER};
    border: 1px solid {ACCENT_HOVER};
}}
QPushButton#Primary:disabled {{
    background-color: {ACCENT_DIM};
    border: 1px solid {ACCENT_DIM};
    color: {TEXT_MUTED};
}}

/* --- Inputs --- */
QLineEdit, QComboBox {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    selection-background-color: {BG_SELECTED};
    color: {TEXT_PRIMARY};
}}

/* --- Drop zone --- */
QFrame#DropZone {{
    background-color: {BG_CARD};
    border: 2px dashed {BORDER_STRONG};
    border-radius: 12px;
}}
QFrame#DropZoneActive {{
    background-color: {BG_CARD};
    border: 2px dashed {ACCENT};
    border-radius: 12px;
}}
QLabel#DropZoneText {{
    color: {TEXT_SECONDARY};
    font-size: 14px;
}}
QLabel#DropZoneHint {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}

/* --- Tables --- */
QTableView, QTreeView {{
    background-color: {BG_CARD};
    alternate-background-color: {BG_APP};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: {BG_SIDEBAR};
    color: {TEXT_SECONDARY};
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.5px;
}}
QTableView::item {{
    padding: 6px 8px;
}}

/* --- Log view (QTextEdit) --- */
QTextEdit#Log {{
    background-color: #141312;
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_PRIMARY};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 8px;
}}

/* --- Scrollbars --- */
QScrollBar:vertical {{
    background: {BG_APP};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {BG_APP};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* --- Status chips --- */
QLabel#ChipOK {{
    background-color: rgba(127,174,110,0.18);
    color: {SUCCESS};
    border: 1px solid rgba(127,174,110,0.35);
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#ChipWarn {{
    background-color: rgba(224,176,96,0.18);
    color: {WARNING};
    border: 1px solid rgba(224,176,96,0.35);
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#ChipError {{
    background-color: rgba(212,106,106,0.18);
    color: {ERROR};
    border: 1px solid rgba(212,106,106,0.35);
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}}

/* --- Splitter --- */
QSplitter::handle {{
    background-color: {BG_APP};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
"""
