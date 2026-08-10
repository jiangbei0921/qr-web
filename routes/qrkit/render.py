"""二维码渲染层：封装 qrcode 库，支持 PNG / SVG。

接口抽象化：调用方只依赖 render_png / render_svg，不感知底层库。
后续若要切换到 segno（原生 SVG 矢量、彩色、无 Pillow 强依赖），仅改本文件即可。
复用项目现有依赖 qrcode==7.4.2，零新增依赖。
"""
from io import BytesIO
import qrcode
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


def render_png(payload, opts):
    """渲染 PNG 字节流。opts: error_correction/box_size/border/fill_color/back_color/style。"""
    qr = _build_qr(payload, opts)
    fill = opts.get('fill_color', '#000000')
    back = opts.get('back_color', '#FFFFFF')
    drawer = RoundedModuleDrawer() if opts.get('style') == 'rounded' else SquareModuleDrawer()
    img = qr.make_image(fill_color=fill, back_color=back, module_drawer=drawer)
    # qrcode 7.x 在部分样式下返回包装对象，取底层 PIL Image
    if hasattr(img, 'get_image'):
        img = img.get_image()
    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return buf.getvalue()


def render_svg(payload, opts):
    """渲染 SVG 字符串（qrcode 7.x 返回 bytes，这里统一为 str）。"""
    qr = _build_qr(payload, opts)
    img = qr.make_image(image_factory=SvgPathImage)
    out = img.to_string()
    if isinstance(out, bytes):
        return out.decode('utf-8')
    return out
