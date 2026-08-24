"""二维码生成 API 蓝图（P0 内核接入层）。

端点：
- GET  /api/qr/types    返回自描述 schema（前端据此动态生成表单）
- POST /api/qr/generate 单入口多格式生成（PNG / SVG）

统一返回 JSON：PNG 含 data_uri 可直接 <img src>；SVG 含 svg 字符串。
入参经校验后交给类型系统，畸形输入返回 400，错误结构统一 {error, message}。
"""
import base64
import io
import re
import zipfile
import datetime
from flask import Blueprint, request, jsonify, send_file
from .types import registry, QRValidationError
from .render import render_png, render_svg, render_pdf

MAX_BATCH = 100

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
    logo = options.get('logo')
    if isinstance(logo, str) and logo.strip():
        opts['logo'] = logo.strip()
    opts['transparent_bg'] = bool(options.get('transparent_bg'))
    return opts


@qrkit_bp.route('/api/qr/types', methods=['GET'])
def qr_types():
    """能力发现：返回所有支持的类型及其字段 schema。"""
    return jsonify({'types': registry.describe()})


def _make_one(qtype, fields, options, fmt):
    """单条生成核心：校验 -> 规范编码 -> 渲染。返回 {payload, png|svg|pdf, fmt}；失败抛 QRValidationError。"""
    builder = registry.get(qtype)
    if not builder:
        raise QRValidationError(f'不支持的二维码类型: {qtype}')
    cleaned = builder.validate(fields)
    payload = builder.build_payload(cleaned)
    if not payload or not payload.strip():
        raise QRValidationError('二维码内容为空')
    if fmt == 'svg':
        return {'payload': payload, 'svg': render_svg(payload, options), 'fmt': 'svg'}
    if fmt == 'pdf':
        return {'payload': payload, 'pdf': render_pdf(payload, options), 'fmt': 'pdf'}
    return {'payload': payload, 'png': render_png(payload, options), 'fmt': 'png'}


@qrkit_bp.route('/api/qr/generate', methods=['POST'])
def qr_generate():
    """单入口生成：{type, fields, options?, format?} -> {format, payload, image_base64/data_uri | svg}。"""
    data = request.get_json(silent=True) or {}
    qtype = data.get('type')
    fields = data.get('fields') or {}
    options = _clean_options(data.get('options'))
    fmt = str(data.get('format') or 'png').lower()
    if fmt not in ('png', 'svg', 'pdf'):
        fmt = 'png'
    try:
        one = _make_one(qtype, fields, options, fmt)
    except QRValidationError as e:
        return jsonify({'error': 'validation', 'message': str(e)}), 400

    if one['fmt'] == 'svg':
        return jsonify({'format': 'svg', 'payload': one['payload'], 'svg': one['svg']})

    if one['fmt'] == 'pdf':
        b64 = base64.b64encode(one['pdf']).decode('ascii')
        return jsonify({
            'format': 'pdf',
            'payload': one['payload'],
            'pdf_base64': b64,
            'data_uri': f'data:application/pdf;base64,{b64}',
        })

    b64 = base64.b64encode(one['png']).decode('ascii')
    return jsonify({
        'format': 'png',
        'payload': one['payload'],
        'image_base64': b64,
        'data_uri': f'data:image/png;base64,{b64}',
    })


@qrkit_bp.route('/api/qr/batch', methods=['POST'])
def qr_batch():
    """批量生成：{items:[{type, fields, options?}], format?} -> ZIP 打包下载（含 README 清单记录每条结果）。"""
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list) or not items:
        return jsonify({'error': 'empty', 'message': '批量数据为空'}), 400
    if len(items) > MAX_BATCH:
        return jsonify({'error': 'too_many', 'message': f'单次最多生成 {MAX_BATCH} 个'}), 400
    fmt = str(data.get('format') or 'png').lower()
    if fmt not in ('png', 'svg', 'pdf'):
        fmt = 'png'
    global_opts = _clean_options(data.get('options') or {})

    mem = io.BytesIO()
    readme = [
        'ZhiQR 批量导出',
        f'生成时间: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'格式: {fmt.upper()}',
    ]
    ok = 0
    failed = 0
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, it in enumerate(items, 1):
            qtype = it.get('type') if isinstance(it, dict) else None
            fields = it.get('fields') if isinstance(it, dict) else None
            opt = _clean_options({**global_opts, **(it.get('options') or {})})
            idx = f'{i:03d}'
            try:
                one = _make_one(qtype, fields or {}, opt, fmt)
                fname = f'{idx}-{qtype}.{fmt}'
                if fmt == 'svg':
                    z.writestr(fname, one['svg'])
                elif fmt == 'pdf':
                    z.writestr(fname, one['pdf'])
                else:
                    z.writestr(fname, one['png'])
                ok += 1
                readme.append(f'{fname}\t{one["payload"]}')
            except QRValidationError as e:
                failed += 1
                readme.append(f'# 第 {i} 行 ({qtype}): {e}')
            except Exception:
                failed += 1
                readme.append(f'# 第 {i} 行 ({qtype}): 生成失败')
        readme.insert(3, f'成功: {ok}  失败: {failed}')
        readme.append('')
        readme.append('（以 # 开头的行为失败条目，已跳过未写入压缩包）')
        z.writestr('README.txt', '\n'.join(readme))
    mem.seek(0)
    return send_file(mem, mimetype='application/zip', as_attachment=True, download_name='zhiqr-batch.zip')
