"""二维码渲染层：封装 qrcode 库，支持 PNG / SVG / PDF，含 Logo 叠加与透明背景。

接口抽象化：调用方只依赖 render_png / render_svg / render_pdf，不感知底层库。
后续若要切换到 segno（原生 SVG 矢量、彩色、无 Pillow 强依赖），仅改本文件即可。
复用项目现有依赖 qrcode==7.4.2，零新增依赖。
"""
import base64
import re
from io import BytesIO
import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import (
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
    ERROR_CORRECT_H,
)
from qrcode.image.svg import SvgPathImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer, SquareModuleDrawer

ERROR_MAP = {
    'L': ERROR_CORRECT_L,
    'M': ERROR_CORRECT_M,
    'Q': ERROR_CORRECT_Q,
    'H': ERROR_CORRECT_H,
}

_LOGO_RATIO = 0.22
_LOGO_DATA_RE = re.compile(r'^data:image/[^;]+;base64,(.+)$', re.DOTALL)


def _build_qr(payload, opts):
    ec = ERROR_MAP.get((opts.get('error_correction') or 'M').upper(), ERROR_CORRECT_M)
    qr = qrcode.QRCode(
        version=None,  # None = 自动适配数据长度
        error_correction=ec,
        box_size=opts.get('box_size', 10),
        border=opts.get('border', 4),
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr


def _decode_logo(logo):
    """把前端传入的 data URI 解码为 PIL RGBA 图；非法返回 None。"""
    if not logo or not isinstance(logo, str):
        return None
    m = _LOGO_DATA_RE.match(logo.strip())
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(1))
        return Image.open(BytesIO(raw)).convert('RGBA')
    except Exception:
        return None


def _apply_logo(img, logo_img, ratio=_LOGO_RATIO):
    """在二维码中心叠加 Logo：白底圆角保证可扫性。img 必须为 RGB/RGBA。"""
    w, h = img.size
    lw = max(24, int(min(w, h) * ratio))
    logo_img = logo_img.resize((lw, lw), Image.LANCZOS)
    pad = max(6, int(lw * 0.08))
    left, top = w // 2 - lw // 2, h // 2 - lw // 2
    box = (left - pad, top - pad, left + lw + pad, top + lw + pad)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, radius=pad, fill=(255, 255, 255, 255))
    img.paste(logo_img, (left, top), logo_img)
    return img


def _maybe_transparent(img, back_color):
    """把背景色像素变为透明（仅当请求透明背景时调用）。"""
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    px = img.load()
    bw, bh = img.size
    target = tuple(int(back_color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    for x in range(bw):
        for y in range(bh):
            if px[x, y] == target:
                px[x, y] = (255, 255, 255, 0)
    return img


def render_png(payload, opts):
    """渲染 PNG 字节流。opts: error_correction/box_size/border/fill_color/back_color/style/size/logo/transparent_bg。"""
    qr = _build_qr(payload, opts)
    fill = opts.get('fill_color', '#000000')
    back = opts.get('back_color', '#FFFFFF')
    transparent = bool(opts.get('transparent_bg'))
    drawer = RoundedModuleDrawer() if opts.get('style') == 'rounded' else SquareModuleDrawer()
    img = qr.make_image(fill_color=fill, back_color=back if not transparent else 'white',
                        module_drawer=drawer)
    if hasattr(img, 'get_image'):  # qrcode 7.x 包装对象取底层 PIL Image
        img = img.get_image()
    if transparent:
        img = _maybe_transparent(img, back)
    if img.mode != 'RGBA' and not transparent:
        img = img.convert('RGBA') if img.mode == 'P' else img
    size = opts.get('size')
    if size and size > 0:
        img = img.resize((size, size), Image.LANCZOS)
    logo_img = _decode_logo(opts.get('logo'))
    if logo_img is not None:
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        img = _apply_logo(img, logo_img)
    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return buf.getvalue()


def render_svg(payload, opts):
    """渲染 SVG 字符串（qrcode 7.x 返回 bytes，这里统一为 str）。"""
    qr = _build_qr(payload, opts)
    fill = opts.get('fill_color', '#000000')
    back = opts.get('back_color', '#FFFFFF')
    img = qr.make_image(image_factory=SvgPathImage, fill_color=fill, back_color=back)
    out = img.to_string()
    if isinstance(out, bytes):
        return out.decode('utf-8')
    return out


def render_pdf(payload, opts):
    """渲染 PDF 字节流（基于 PNG，强制白底以保证可读性）。"""
    no_logo = dict(opts)
    no_logo['transparent_bg'] = False
    png = render_png(payload, no_logo)
    img = Image.open(BytesIO(png)).convert('RGB')
    buf = BytesIO()
    img.save(buf, 'PDF', resolution=300.0)
    buf.seek(0)
    return buf.getvalue()
