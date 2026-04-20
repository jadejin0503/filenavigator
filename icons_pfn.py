"""
PFN 图标模块：Ant Design 风格图标，14px，支持按类型/层级区分颜色。
"""
import os
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath
from PyQt6.QtCore import Qt, QRectF

try:
    from PyQt6.QtSvg import QSvgRenderer
    _USE_SVG = True
except ImportError:
    _USE_SVG = False

ICON_SIZE = 14

# 文件夹填充 (FolderFilled) - 主色
_FOLDER_FILLED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<path fill="{color}" d="M880 298.4H521L405.7 186.2a8.15 8.15 0 0 0-5.5-2.2H144c-17.7 0-32 14.3-32 32v592c0 17.7 14.3 32 32 32h736c17.7 0 32-14.3 32-32V330.4c0-17.7-14.3-32-32-32z"/>
</svg>'''

# 文件夹描边 (FolderOutlined) - 次要色
_FOLDER_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<path fill="none" stroke="{color}" stroke-width="56" stroke-linejoin="round" stroke-linecap="round" d="M880 298.4H521L405.7 186.2c-5.8-4.9-13.8-7.8-22.2-7.8H144c-17.7 0-32 14.3-32 32v592c0 17.7 14.3 32 32 32h736c17.7 0 32-14.3 32-32V330.4c0-17.7-14.3-32-32-32z"/>
</svg>'''

# 文件 XML
_FILE_XML = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<path fill="{color}" d="M854.6 288.6L639.4 73.4c-6-6-14.1-9.4-22.6-9.4H192c-17.7 0-32 14.3-32 32v832c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V311.3c0-8.5-3.4-16.7-9.4-22.7zM400 402c0-4.4 3.6-8 8-8h208c4.4 0 8 3.6 8 8v48c0 4.4-3.6 8-8 8H408c-4.4 0-8-3.6-8-8v-48zm0 160v48c0 4.4 3.6 8 8 8h208c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8H408c-4.4 0-8 3.6-8 8zm416 224H208V148h216v168c0 17.7 14.3 32 32 32h168v250z"/>
</svg>'''

# 文件 Excel
_FILE_EXCEL = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<path fill="{color}" d="M854.6 288.6L639.4 73.4c-6-6-14.1-9.4-22.6-9.4H192c-17.7 0-32 14.3-32 32v832c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V311.3c0-8.5-3.4-16.7-9.4-22.7zM400 402c0-4.4 3.6-8 8-8h208c4.4 0 8 3.6 8 8v48c0 4.4-3.6 8-8 8H408c-4.4 0-8-3.6-8-8v-48zm0 160v48c0 4.4 3.6 8 8 8h208c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8H408c-4.4 0-8 3.6-8 8zm416 224H208V148h216v168c0 17.7 14.3 32 32 32h168v250z"/>
</svg>'''

# 文件 PDF
_FILE_PDF = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<path fill="{color}" d="M854.6 288.6L639.4 73.4c-6-6-14.1-9.4-22.6-9.4H192c-17.7 0-32 14.3-32 32v832c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V311.3c0-8.5-3.4-16.7-9.4-22.7zM400 402c0-4.4 3.6-8 8-8h208c4.4 0 8 3.6 8 8v48c0 4.4-3.6 8-8 8H408c-4.4 0-8-3.6-8-8v-48zm0 160v48c0 4.4 3.6 8 8 8h208c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8H408c-4.4 0-8 3.6-8 8zm416 224H208V148h216v168c0 17.7 14.3 32 32 32h168v250z"/>
</svg>'''

# 文件 Word
_FILE_WORD = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<path fill="{color}" d="M854.6 288.6L639.4 73.4c-6-6-14.1-9.4-22.6-9.4H192c-17.7 0-32 14.3-32 32v832c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V311.3c0-8.5-3.4-16.7-9.4-22.7zM400 402c0-4.4 3.6-8 8-8h208c4.4 0 8 3.6 8 8v48c0 4.4-3.6 8-8 8H408c-4.4 0-8-3.6-8-8v-48zm0 160v48c0 4.4 3.6 8 8 8h208c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8H408c-4.4 0-8 3.6-8 8zm416 224H208V148h216v168c0 17.7 14.3 32 32 32h168v250z"/>
</svg>'''

# 普通文件
_FILE_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<path fill="{color}" d="M854.6 288.6L639.4 73.4c-6-6-14.1-9.4-22.6-9.4H192c-17.7 0-32 14.3-32 32v832c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V311.3c0-8.5-3.4-16.7-9.4-22.7zM400 402c0-4.4 3.6-8 8-8h208c4.4 0 8 3.6 8 8v48c0 4.4-3.6 8-8 8H408c-4.4 0-8-3.6-8-8v-48zm0 160v48c0 4.4 3.6 8 8 8h208c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8H408c-4.4 0-8 3.6-8 8zm416 224H208V148h216v168c0 17.7 14.3 32 32 32h168v250z"/>
</svg>'''

# HomeOutlined / SendOutlined / PushpinOutlined / BarsOutlined / 右侧黄色文件夹
_HOME_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M946.5 505L560.1 118.8l-25.9-25.9a31.5 31.5 0 0 0-44.4 0L77.5 505a63.9 63.9 0 0 0-18.8 46c.4 35.2 29.7 63.6 65 63.6h42.5V940h691.8V614.6h42.5c35.3 0 64.6-28.3 65-63.6a63.9 63.9 0 0 0-18.8-46zM568 868H456V664h112v204zm217.9-325.7V868H632V640c0-22.1-17.9-40-40-40H432c-22.1 0-40 17.9-40 40v228H238.1V542.3h-96l370-369.7 23.1 23.1L882 542.3h-96.1z"/></svg>'''
_SEND_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M931.4 498.9L94.9 79.5c-3.4-1.7-7.3-2.1-11-1.2a15.99 15.99 0 0 0-11.7 19.3l86.2 352.2c1.3 5.3 5.2 9.6 10.4 12.3l147.7 77.7 147.7 77.7c5.2 2.7 9.9 7.4 12.3 12.8l86.2 352.2c2.8 11.4 15.7 18.2 27.1 15.4 3.7-.9 7-2.9 9.4-5.8l173.4-192.3c3-3.3 4.9-7.6 4.9-12.2 0-4.7-1.9-9-4.9-12.2L931.4 498.9zM170.8 124.9l151.6 619.2-151.6-79.8V124.9zm693.4 361.5l-147.7-77.7-147.7-77.7-151.6 79.8 151.6 619.2 147.7-77.7 147.7-77.7 151.6-79.8-151.6-619.2z"/></svg>'''
_PUSHPIN_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M878.3 392.1L631.9 145.7c-6.5-6.5-15-9.7-23.5-9.7s-17 3.2-23.5 9.7L423.8 306.9c-12.2-1.4-24.5-2-36.8-2-65.4 0-128.9 21.6-177.2 62.7-3.4 2.8-6.7 5.8-9.9 8.9-7.1 7.1-7.1 18.6 0 25.6l181 181 181 181c3.3 3.3 7.4 4.9 11.6 4.9 4.2 0 8.3-1.7 11.6-4.9 3.1-3.1 6.1-6.5 8.9-9.9 41.1-48.3 62.7-111.8 62.7-177.2 0-12.3-.6-24.6-2-36.8l161.2-161.2c12.9 12.9 12.9 33.8 0 46.8L565.2 878.3c-6.5 6.5-6.5 17 0 23.5 3.2 3.2 7.4 4.9 11.7 4.9s8.5-1.6 11.7-4.9l313.4-313.4c6.5-6.5 6.5-17 0-23.5l-24.2-24.2-313.4 313.4c-6.5 6.5-6.5 17 0 23.5 3.2 3.2 7.4 4.9 11.7 4.9s8.5-1.6 11.7-4.9l313.4-313.4c6.5-6.5 6.5-17 0-23.5L878.3 392.1z"/></svg>'''
_BARS_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M160 256h704v64H160zm0 224h704v64H160zm0 224h704v64H160z"/></svg>'''
_FOLDER_YELLOW = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M880 298.4H521L405.7 186.2a8.15 8.15 0 0 0-5.5-2.2H144c-17.7 0-32 14.3-32 32v592c0 17.7 14.3 32 32 32h736c17.7 0 32-14.3 32-32V330.4c0-17.7-14.3-32-32-32z"/></svg>'''

# HeartOutlined / ProductOutlined (Ant Design 风格)
_HEART_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M923 283.6a260.04 260.04 0 0 0-56.9-82.8 264.4 264.4 0 0 0-84-55.5A265.34 265.34 0 0 0 679.7 125c-49.3 0-97.4 13.5-139.2 39-10 6.1-19.5 12.8-28.5 15.8-9-3-18.5-9.7-28.5-15.8-41.8-25.5-89.9-39-139.2-39-35.5 0-69.9 6.8-102.4 20.3-31.4 13-59.7 31.7-84 55.5a258.44 258.44 0 0 0-56.9 82.8c-13.9 32.3-21 66.6-21 101.9 0 33.3 6.8 68 20.3 103.3 11.3 29.5 27.5 60.1 48.2 91 32.8 48.9 77.9 99.9 133.9 151.6 92.8 85.7 184.7 144.9 188.6 147.3l23.7 15.2c10.5 6.7 24 6.7 34.5 0l23.7-15.2c3.9-2.5 95.7-61.6 188.6-147.3 56-51.7 101.1-102.7 133.9-151.6 20.7-30.9 37-61.5 48.2-91 13.5-35.3 20.3-70 20.3-103.3 0-35.3-7.1-69.6-21-101.9zM512 814.8S156 586.7 156 385.5C156 283.6 240.3 201 344.3 201c73.1 0 136.5 40.8 167.7 104a214 214 0 0 1 167.7-104c104 0 188.3 82.6 188.3 184.5 0 201.2-356 429.3-356 429.3z"/></svg>'''
_PRODUCT_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M864 128H160c-17.7 0-32 14.3-32 32v704c0 17.7 14.3 32 32 32h704c17.7 0 32-14.3 32-32V160c0-17.7-14.3-32-32-32zM160 864V160h704v704H160z"/><path fill="{color}" d="M384 384h256v64H384zm0 128h256v64H384zm0 128h128v64H384z"/></svg>'''

# CheckCircleOutlined / HomeOutlined（项目根）
_CHECK_CIRCLE_OUTLINED = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path fill="{color}" d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm193.5 301.7l-210.6 292a31.8 31.8 0 0 1-51.7 0L318.5 484.9c-3.8-5.3 0-12.7 6.5-12.7h46.9c10.2 0 19.9 4.9 25.9 13.3l71.2 98.8 157.2-218c6-8.3 15.6-13.3 25.9-13.3H699c6.5 0 10.3 7.4 6.5 12.7z"/></svg>'''

_COLORS = {
    # 更“现代/柔和”的一套颜色（偏中性，避免过饱和导致视觉噪音）
    "primary": "#2F6BFF",
    "secondary": "#667085",
    "success": "#00B42A",
    "danger": "#F53F3F",
    "yellow_folder": "#FFB100",  # 黄色文件夹（略降噪）
    "heart": "#F56C6C",          # 心形 低饱和红
    "red_soft": "#F56C6C",       # 辅助红
    "green_soft": "#67C23A",     # 辅助绿
    "blue_soft": "#409EFF",      # 辅助蓝
    "neutral_bg": "#F5F7FA",
    "neutral_line": "#E5E6EB",
    "neutral_text": "#4E5969",
    "xml_gray": "#909399",
    "sas_yellow": "#E6A23C",
}

_icon_cache = {}
_pm_logo_pixmap_cache = {}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """#F56C6C, 0.6 -> rgba(245,108,108,0.6)"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return hex_color


def _svg_to_icon(svg_tpl: str, color: str, size: int = ICON_SIZE, opacity: float = 1.0) -> QIcon:
    key = f"{svg_tpl[:50]}_{color}_{size}_{opacity}"
    if key in _icon_cache:
        return _icon_cache[key]
    if not _USE_SVG:
        icon = QIcon()
    else:
        try:
            use_opacity = opacity
            if "rgba(" in color:
                parts = color.replace("rgba(", "").replace(")", "").split(",")
                if len(parts) >= 4:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    use_opacity = float(parts[3].strip())
                    hex_color = "#{:02x}{:02x}{:02x}".format(r, g, b)
                else:
                    hex_color = color
            else:
                hex_color = color if color.startswith("#") else color
            svg = svg_tpl.format(color=hex_color)
            if use_opacity < 1.0 and "fill-opacity" not in svg:
                import re
                svg = re.sub(r'(<path\s+fill="[^"]+")(\s+)', r'\1 fill-opacity="{:g}"\2'.format(use_opacity), svg, count=1)
            renderer = QSvgRenderer(svg.encode("utf-8"))
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            icon = QIcon(pixmap)
        except Exception:
            icon = QIcon()
    _icon_cache[key] = icon
    return icon


def icon_folder_root():
    """一级根文件夹：FolderFilled #165DFF"""
    return _svg_to_icon(_FOLDER_FILLED, _hex_to_rgba(_COLORS["primary"], 0.92))


def icon_folder_sub():
    """二级及以下子文件夹：FolderOutlined #86909C"""
    return _svg_to_icon(_FOLDER_OUTLINED, _hex_to_rgba(_COLORS["secondary"], 0.90))


def icon_file_xml():
    """XML 文件 #00B42A"""
    return _svg_to_icon(_FILE_XML, _COLORS["success"])


def icon_file_excel():
    """Excel 文件 #00B42A"""
    return _svg_to_icon(_FILE_EXCEL, _COLORS["success"])


def icon_file_pdf():
    """PDF 文件 #F53F3F"""
    return _svg_to_icon(_FILE_PDF, _COLORS["danger"])


def icon_file_word():
    """Word 文件 #165DFF"""
    return _svg_to_icon(_FILE_WORD, _COLORS["primary"])


def icon_file_default():
    """其他文件 #86909C"""
    return _svg_to_icon(_FILE_OUTLINED, _hex_to_rgba(_COLORS["secondary"], 0.92))


def icon_for_file(path: str):
    """根据文件路径返回对应图标"""
    ext = (path or "").lower().split(".")[-1]
    if ext == "xml":
        return icon_file_xml()
    if ext in ("xlsx", "xls", "csv"):
        return icon_file_excel()
    if ext == "pdf":
        return icon_file_pdf()
    if ext in ("doc", "docx"):
        return icon_file_word()
    return icon_file_default()


def icon_for_folder(is_root: bool):
    """根据层级返回文件夹图标"""
    return icon_folder_root() if is_root else icon_folder_sub()


def icon_home_outlined():
    """收藏项目库：HomeOutlined，低透明度"""
    return _svg_to_icon(_HOME_OUTLINED, _COLORS["secondary"])


def icon_send_outlined():
    """CSR 级别：SendOutlined 灰色"""
    return _svg_to_icon(_SEND_OUTLINED, _COLORS["secondary"])


def icon_pushpin_outlined(size: int = 16, color: str = "#F53F3F", alpha: float = 0.9):
    """PushpinOutlined（默认红色，用于置顶语义）。"""
    return _svg_to_icon(_PUSHPIN_OUTLINED, _hex_to_rgba(color, alpha), size)


def icon_bars_outlined(size: int = 16, color: str = "#F53F3F", alpha: float = 0.95):
    """BarsOutlined（默认红色）。"""
    return _svg_to_icon(_BARS_OUTLINED, _hex_to_rgba(color, alpha), size)


def icon_folder_yellow():
    """黄色文件夹 #FCC300"""
    return _svg_to_icon(_FOLDER_YELLOW, _hex_to_rgba(_COLORS["yellow_folder"], 0.92))


def icon_heart_outlined(size: int = 16):
    """收藏项目库：HeartOutlined #F56C6C 透明度 0.8"""
    return _svg_to_icon(_HEART_OUTLINED, _hex_to_rgba(_COLORS["heart"], 0.8), size)


def pfn_header_logo_pixmap(size: int = 24, radius: int = 7) -> QPixmap:
    """左侧「项目管理栏」标题旁：优先使用 assets/pfn_logo_source.png（圆角卡片），缺失时回退心形图标。"""
    key = (size, radius)
    if key in _pm_logo_pixmap_cache:
        return _pm_logo_pixmap_cache[key]
    base = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(base, "assets", "pfn_logo_source.png")
    pm = None
    if os.path.isfile(png_path):
        try:
            raw = QPixmap(png_path)
            if not raw.isNull():
                scaled = raw.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                out = QPixmap(size, size)
                out.fill(Qt.GlobalColor.transparent)
                p = QPainter(out)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                path = QPainterPath()
                path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
                p.setClipPath(path)
                x = (size - scaled.width()) // 2
                y = (size - scaled.height()) // 2
                p.drawPixmap(x, y, scaled)
                p.end()
                pm = out
        except Exception:
            pm = None
    if pm is None:
        pm = icon_heart_outlined(size).pixmap(size, size)
    _pm_logo_pixmap_cache[key] = pm
    return pm


def icon_product_outlined(size: int = 14):
    """Documents 根节点：ProductOutlined #4E5969 0.8"""
    return _svg_to_icon(_PRODUCT_OUTLINED, _hex_to_rgba(_COLORS["neutral_text"], 0.8), size)


def icon_send_outlined(size: int = 12):
    """CSR 层级（已弃用，改用 icon_check_circle_outlined）"""
    return _svg_to_icon(_SEND_OUTLINED, _hex_to_rgba(_COLORS["secondary"], 0.8), size)


def icon_check_circle_outlined(size: int = 12):
    """CSR 层级 csr_01/csr_02：CheckCircleOutlined #67C23A 0.8"""
    return _svg_to_icon(_CHECK_CIRCLE_OUTLINED, _hex_to_rgba(_COLORS["green_soft"], 0.8), size)


def icon_home_outlined(size: int = 14):
    """项目根级别 SHR6508_301 等：HomeOutlined #409EFF 0.8"""
    return _svg_to_icon(_HOME_OUTLINED, _hex_to_rgba(_COLORS["blue_soft"], 0.8), size)


def icon_file_excel_outlined(size: int = 12):
    """二级子文件夹：FileExcelOutlined #67C23A 0.7"""
    return _svg_to_icon(_FILE_EXCEL, _hex_to_rgba(_COLORS["green_soft"], 0.7), size)


def icon_file_pdf_soft(size: int = 14, alpha: float = 0.9):
    """PDF 红 #F56C6C 0.9"""
    return _svg_to_icon(_FILE_PDF, _COLORS["red_soft"], size, alpha)


def icon_file_word_soft(size: int = 14, alpha: float = 0.9):
    """Word 蓝 #409EFF 0.9"""
    return _svg_to_icon(_FILE_WORD, _COLORS["blue_soft"], size, alpha)


def icon_file_excel_soft(size: int = 14, alpha: float = 0.9):
    """Excel 绿 #67C23A 0.9"""
    return _svg_to_icon(_FILE_EXCEL, _COLORS["green_soft"], size, alpha)


def icon_file_xml_soft(size: int = 14, alpha: float = 0.9):
    """XML 灰 #909399 0.9"""
    return _svg_to_icon(_FILE_XML, _COLORS["xml_gray"], size, alpha)


def icon_file_sas_soft(size: int = 14, alpha: float = 0.9):
    """SAS 黄 #E6A23C 0.9"""
    return _svg_to_icon(_FILE_OUTLINED, _COLORS["sas_yellow"], size, alpha)


def icon_file_default_soft(size: int = 14, alpha: float = 0.9):
    """其他 #86909C 0.9"""
    return _svg_to_icon(_FILE_OUTLINED, _COLORS["secondary"], size, alpha)


def icon_for_file_soft(path: str, size: int = 14):
    """右侧文件树按类型返回图标（低饱和 0.9 透明度）"""
    ext = (path or "").lower().split(".")[-1]
    a = 0.9
    if ext == "pdf":
        return icon_file_pdf_soft(size, a)
    if ext in ("doc", "docx"):
        return icon_file_word_soft(size, a)
    if ext in ("xlsx", "xls", "csv"):
        return icon_file_excel_soft(size, a)
    if ext == "xml":
        return icon_file_xml_soft(size, a)
    if ext == "sas":
        return icon_file_sas_soft(size, a)
    return icon_file_default_soft(size, a)
