"""二维码生成 API 蓝图（P0 内核接入层）。

端点：
- GET  /api/qr/types    返回自描述 schema（前端据此动态生成表单）
- POST /api/qr/generate 单入口多格式生成（PNG / SVG）

统一返回 JSON：PNG 含 data_uri 可直接 <img src>；SVG 含 svg 字符串。
入参经校验后交给类型系统，畸形输入返回 400，错误结构统一 {error, message}。
"""
import base64
import re
from flask import Blueprint, request, jsonify
from .types import registry, QRValidationError
from .render import render_png, render_svg

qrkit_bp = Blueprint('qrkit', __name__)

_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
_ALLOWED_EC = ('L', 'M', 'Q', 'H')


def _clean_options(options):
    """清洗并约束渲染选项，避免非法值导致运行时异常。"""
    options = options or {}
    opts = {}
    ec = str(options.get('error_correction', 'M')).upper()
    opts['error_correction'] = ec if ec in _ALLOWED_EC else 'M'
    for k in ('fill_color', 'back_color'):
        v = options.get(k)
        opts[k] = v if isinstance(v, str) and _COLOR_RE.match(v) else ('#000000' if k == 'fill_color' else '#FFFFFF')
    try:
        bs = int(options.get('box_size', 10))
    except (TypeError, ValueError):
        bs = 10
    opts['box_size'] = max(2, min(40, bs))
    try:
        bd = int(options.get('border', 4))
    except (TypeError, ValueError):
        bd = 4
    opts['border'] = max(0, min(20, bd))
    style = options.get('style')
    if style in ('rounded', 'square'):
        opts['style'] = style
    try:
        sz = int(options.get('size', 0))
    except (TypeError, ValueError):
        sz = 0
    opts['size'] = sz if 64 <= sz <= 4096 else 0
    return opts


@qrkit_bp.route('/api/qr/types', methods=['GET'])
def qr_types():
    """能力发现：返回所有支持的类型及其字段 schema。"""
    return jsonify({'types': registry.describe()})


@qrkit_bp.route('/api/qr/generate', methods=['POST'])
def qr_generate():
    """单入口生成：{type, fields, options?, format?} -> {format, payload, image_base64/data_uri | svg}。"""
    data = request.get_json(silent=True) or {}
    qtype = data.get('type')
    fields = data.get('fields') or {}
    options = _clean_options(data.get('options'))

    builder = registry.get(qtype)
    if not builder:
        return jsonify({'error': 'unknown_type', 'message': f'不支持的二维码类型: {qtype}'}), 400

    try:
        cleaned = builder.validate(fields)
        payload = builder.build_payload(cleaned)
    except QRValidationError as e:
        return jsonify({'error': 'validation', 'message': str(e)}), 400

    if not payload or not payload.strip():
        return jsonify({'error': 'empty', 'message': '二维码内容为空'}), 400

    fmt = str(data.get('format') or 'png').lower()
    if fmt == 'svg':
        svg_text = render_svg(payload, options)
        return jsonify({'format': 'svg', 'payload': payload, 'svg': svg_text})

    png_bytes = render_png(payload, options)
    b64 = base64.b64encode(png_bytes).decode('ascii')
    return jsonify({
        'format': 'png',
        'payload': payload,
        'image_base64': b64,
        'data_uri': f'data:image/png;base64,{b64}',
    })
