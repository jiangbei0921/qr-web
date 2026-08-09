"""
open_api.py - 开放平台（OpenAPI）模块
为第三方开发者提供标准化的API接口，支持API Key和JWT两种认证方式。

企业客户可以通过OpenAPI将自己的系统与智码云平台对接，
实现二维码的自动化创建、管理和数据查询。

主要功能：
1. OpenAPI认证：支持API Key和JWT（JSON Web Token）两种方式
2. 二维码管理：通过API创建、查询二维码
3. 扫码数据：获取二维码的扫码统计
4. 表单提交：查询表单提交记录
5. 应用管理：创建和管理API应用（App Key/Secret）
6. OAuth2授权：支持第三方OAuth2授权流程
7. 工作流引擎：触发和执行工作流

认证方式说明：
- API Key：简单直接，适合服务器端调用
- JWT Token：更安全，适合客户端调用，有过期时间
- 两种方式可以同时使用，系统自动识别
"""
import json
import secrets
import hashlib
import hmac
import base64
import time
import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, redirect, g, render_template
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, parse_pagination,
    workflow_trigger_after_scan,
    workflow_trigger_after_qrcode_create,
    generate_short_uuid
)
from routes.workflow_engine import WorkflowEngine

open_api_bp = Blueprint('open_api', __name__)


# ============ OpenAPI 辅助函数 ============

def _openapi_generate_app_key():
    """生成应用密钥（App Key）
    
    App Key 是API调用的"用户名"，公开传输，用于识别是哪个应用在调用API。
    格式：ak_ + 32位随机十六进制字符串
    示例：ak_a1b2c3d4e5f6...
    """
    return 'ak_' + secrets.token_hex(16)


def _openapi_generate_secret():
    """生成应用密钥（App Secret）
    
    App Secret 是API调用的"密码"，必须保密存储，用于签名验证。
    格式：sk_ + 43位随机URL安全字符串
    示例：sk_ABC123def456...
    """
    return 'sk_' + secrets.token_urlsafe(32)


def _openapi_row_to_dict(row):
    """将sqlite3.Row转换为普通字典
    
    sqlite3.Row 对象支持通过列名访问，但不能直接序列化为JSON。
    这个函数将其转换为普通字典，方便JSON序列化。
    """
    if row is None:
        return None
    return dict(row)


def _openapi_generate_jwt(app_id, user_id, org_id, secret, expire_minutes=60):
    """生成JWT令牌（JSON Web Token）
    
    JWT是一种开放标准，用于在各方之间安全地传输信息。
    
    结构说明（三段式，用.分隔）：
    1. Header（头部）：包含算法类型（HS256）和令牌类型（JWT）
    2. Payload（载荷）：包含实际数据，如用户ID、组织ID、过期时间
    3. Signature（签名）：用密钥对前两段签名，防止篡改
    
    示例：eyJhbG...（头部）.eyJzdWI...（载荷）.SflKx...（签名）
    
    参数说明：
    - app_id：应用ID，标识JWT属于哪个应用
    - user_id：用户ID，标识JWT代表哪个用户
    - org_id：组织ID，限制JWT的数据访问范围
    - secret：应用密钥，用于签名
    - expire_minutes：有效期（分钟），默认60分钟
    """
    header = base64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode()).decode().rstrip('=')
    now = int(time.time())
    payload = {
        'iss': 'smartcode',           # 签发者（Issuer）：谁签发的这个JWT
        'sub': str(user_id),          # 主题（Subject）：这个JWT代表谁
        'aud': str(app_id),           # 受众（Audience）：这个JWT给谁用的
        'org_id': org_id,             # 组织ID：限制数据访问范围
        'iat': now,                   # 签发时间（Issued At）：什么时候签发的
        'exp': now + expire_minutes * 60,  # 过期时间（Expiration）：什么时候过期
        'jti': secrets.token_hex(16)  # JWT ID：唯一标识，防止重放攻击
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    signing_input = f'{header}.{payload_b64}'
    # 使用HMAC-SHA256算法对前两段进行签名
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip('=')
    return f'{signing_input}.{signature_b64}'


def _openapi_verify_jwt(token, secret):
    """验证JWT令牌是否合法
    
    验证流程：
    1. 将JWT拆分为三段（header.payload.signature）
    2. 用同样的密钥重新计算签名
    3. 比较签名是否一致（使用hmac.compare_digest防止时序攻击）
    4. 检查是否过期
    
    返回：如果验证通过，返回payload数据；否则返回None
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts
        # 重新计算签名并与传入的签名比较
        expected_sig = hmac.new(secret.encode(), f'{header_b64}.{payload_b64}'.encode(), hashlib.sha256).digest()
        actual_sig = base64.urlsafe_b64decode(signature_b64 + '==')
        # 使用 compare_digest 防止时序攻击（攻击者无法通过测量验证时间来猜测密钥）
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + '=='))
        # 检查是否过期
        if payload.get('exp', 0) < int(time.time()):
            return None
        return payload
    except Exception as e:
        logger.warning(f"JWT验证失败: {e}")
        return None


def openapi_auth(f):
    """OpenAPI 认证装饰器，支持 API Key 和 JWT 两种方式
    
    这个装饰器会拦截所有OpenAPI请求，在执行业务逻辑之前验证身份。
    类似于"门卫"，检查来者有没有合法的"通行证"。
    
    认证流程（按优先级）：
    
    方式一：API Key 认证（简单直接）
    1. 客户端在请求头中设置 X-API-Key
    2. 系统查数据库，找到匹配的 App Key
    3. 验证通过后，将应用信息存入 g 对象（Flask的请求级全局变量）
    
    方式二：JWT Token 认证（更安全）
    1. 客户端在请求头中设置 Authorization: Bearer <token>
    2. 系统遍历所有启用的应用，用每个应用的密钥尝试验证JWT签名
    3. 验证通过后，从JWT中提取用户ID和组织ID
    
    认证结果存储在 g 对象中：
    - g.app_id：应用ID
    - g.org_id：组织ID（数据隔离的关键）
    - g.user_id：用户ID
    - g.auth_type：认证类型（'apikey' 或 'jwt'）
    """
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        api_key = request.headers.get('X-API-Key', '')

        if api_key:
            # 方式一：API Key 认证
            # 从请求头 X-API-Key 中获取密钥，查数据库验证
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM openapps WHERE app_key=? AND is_enabled=1', (api_key,))
                app = c.fetchone()
            if not app:
                return jsonify({'error': '无效的API Key'}), 401
            # 将认证信息存入 g 对象，后续路由函数可以直接使用
            g.app_id = app['id']
            g.org_id = app['org_id']
            g.user_id = app['created_by']
            g.auth_type = 'apikey'
        elif auth_header.startswith('Bearer '):
            # 方式二：JWT Token 认证
            # 从 Authorization 头中提取 Bearer Token
            token = auth_header[7:].strip()
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM openapps WHERE is_enabled=1')
                apps = c.fetchall()
            payload = None
            # 遍历所有应用，用每个应用的密钥尝试验证JWT
            # 因为JWT本身不包含"谁签发的"，所以需要逐个尝试
            for app in apps:
                payload = _openapi_verify_jwt(token, app['app_secret'])
                if payload:
                    g.app_id = app['id']
                    g.org_id = payload.get('org_id', app['org_id'])
                    g.user_id = payload.get('sub')
                    g.auth_type = 'jwt'
                    break
            if not payload:
                return jsonify({'error': '无效的访问令牌'}), 401
        else:
            # 两种认证方式都没有提供，拒绝访问
            return jsonify({'error': '请提供API Key或Bearer Token'}), 401
        return f(*args, **kwargs)
    return decorated


@open_api_bp.route('/openapi/v1/qrcodes/list', methods=['GET'])
@openapi_auth
def openapi_qrcodes_list():
    """分页查询二维码列表"""
    try:
        page, size, offset = parse_pagination()
        keyword = (request.args.get('keyword') or '').strip()
        tag = (request.args.get('tag') or '').strip()

        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE org_id=? AND is_deleted=0'
            params = [g.org_id]
            if keyword:
                where += ' AND (title LIKE ? OR uuid_short LIKE ?)'
                params.extend([f'%{keyword}%', f'%{keyword}%'])
            if tag:
                where += ' AND tag_id IN (SELECT id FROM tags WHERE name=? AND org_id=?)'
                params.extend([tag, g.org_id])

            c.execute(f'SELECT COUNT(*) FROM qrcodes {where}', params)
            total = c.fetchone()[0]

            c.execute(
                f'SELECT id, title, uuid_short, type, scan_count, created_at, updated_at '
                f'FROM qrcodes {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?',
                params + [size, (page - 1) * size]
            )
            items = [_openapi_row_to_dict(r) for r in c.fetchall()]

        return jsonify({'success': True, 'data': {'items': items, 'total': total, 'page': page, 'size': size}})
    except Exception as e:
        logger.error(f"开放API二维码列表查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/qrcodes/<int:qrcode_id>', methods=['GET'])
@openapi_auth
def openapi_qrcode_detail(qrcode_id):
    """查询单个二维码详情"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, title, uuid_short, type, content, scan_count, created_at, updated_at '
                      'FROM qrcodes WHERE id=? AND org_id=? AND is_deleted=0',
                      (qrcode_id, g.org_id))
            item = c.fetchone()
            if not item:
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404
            return jsonify({'success': True, 'data': _openapi_row_to_dict(item)})
    except Exception as e:
        logger.error(f"开放API二维码详情查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/qrcodes/create', methods=['POST'])
@openapi_auth
def openapi_qrcode_create():
    """创建二维码"""
    try:
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'error': _t('error.titleRequired', 'title不能为空')}), 400
        qr_type = data.get('type', 'static')
        content = (data.get('content') or '').strip()

        config = json.dumps({
            'type': qr_type,
            'content': content,
            'error_correction': data.get('error_correction', 'M'),
            'foreground': data.get('foreground', '#000000'),
            'background': data.get('background', '#FFFFFF')
        })

        short_uuid = generate_short_uuid()
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO qrcodes (org_id, title, uuid_short, type, content, config, created_by) '
                'VALUES (?,?,?,?,?,?,?)',
                (g.org_id, title, short_uuid, qr_type, content, config, g.user_id)
            )
            qr_id = c.lastrowid
            conn.commit()

        log_action('openapi_qrcode_create', 'qrcode', qr_id,
                   detail={'title': title, 'type': qr_type})
        return jsonify({'success': True, 'data': {'id': qr_id, 'short_url': short_uuid}})
    except Exception as e:
        logger.error(f"开放API创建二维码失败: {e}")
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@open_api_bp.route('/openapi/v1/qrcodes/<int:qrcode_id>/data', methods=['GET'])
@openapi_auth
def openapi_qrcode_data(qrcode_id):
    """获取二维码扫描数据"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, title, content, type, scan_count FROM qrcodes '
                      'WHERE id=? AND org_id=? AND is_deleted=0',
                      (qrcode_id, g.org_id))
            item = c.fetchone()
            if not item:
                return jsonify({'error': _t('error.qrcodeNotFound')}), 404
            c.execute('SELECT id, scan_time, ip, user_agent FROM scan_logs '
                      'WHERE qrcode_id=? ORDER BY scan_time DESC LIMIT 100',
                      (qrcode_id,))
            scans = [_openapi_row_to_dict(r) for r in c.fetchall()]
        return jsonify({'success': True, 'data': {
            'qrcode': _openapi_row_to_dict(item),
            'recent_scans': scans
        }})
    except Exception as e:
        logger.error(f"开放API二维码数据查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/forms/<int:form_id>/submissions', methods=['GET'])
@openapi_auth
def openapi_form_submissions(form_id):
    """查询表单提交记录"""
    try:
        page, size, offset = parse_pagination()
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM forms WHERE id=? AND org_id=? AND is_deleted=0',
                      (form_id, g.org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound', '表单不存在')}), 404

            c.execute(
                'SELECT id, payload_data, created_at FROM form_submissions WHERE form_id=? '
                'ORDER BY created_at DESC LIMIT ? OFFSET ?',
                (form_id, size, offset)
            )
            items = [_openapi_row_to_dict(r) for r in c.fetchall()]
            c.execute('SELECT COUNT(*) FROM form_submissions WHERE form_id=?',
                      (form_id,))
            total = c.fetchone()[0]
        return jsonify({'success': True, 'data': {'items': items, 'total': total, 'page': page, 'size': size}})
    except Exception as e:
        logger.error(f"开放API表单提交查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/forms/<int:form_id>/submit', methods=['POST'])
@openapi_auth
def openapi_form_submit(form_id):
    """提交表单数据"""
    try:
        data = request.get_json(silent=True) or {}
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM forms WHERE id=? AND org_id=? AND is_deleted=0',
                      (form_id, g.org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound', '表单不存在')}), 404

            c.execute(
                'INSERT INTO form_submissions (form_id, payload_data, submitter_id) VALUES (?,?,?)',
                (form_id, json.dumps(data, ensure_ascii=False), g.user_id)
            )
            sub_id = c.lastrowid
            conn.commit()
        return jsonify({'success': True, 'data': {'id': sub_id}})
    except Exception as e:
        logger.error(f"开放API表单提交失败: {e}")
        return jsonify({'error': _t('error.submitFailed', '提交失败')}), 500



@open_api_bp.route('/openapi/v1/workorders/list', methods=['GET'])
@openapi_auth
def openapi_workorders_list():
    """查询工单列表"""
    try:
        page, size, offset = parse_pagination()
        status = (request.args.get('status') or '').strip()
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE org_id=?'
            params = [g.org_id]
            if status:
                where += ' AND status=?'
                params.append(status)

            c.execute(f'SELECT COUNT(*) FROM workorders {where}', params)
            total = c.fetchone()[0]
            c.execute(
                f'SELECT id, title, status, priority, created_at, updated_at '
                f'FROM workorders {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?',
                params + [size, offset]
            )
            items = [_openapi_row_to_dict(r) for r in c.fetchall()]
        return jsonify({'success': True, 'data': {'items': items, 'total': total, 'page': page, 'size': size}})
    except Exception as e:
        logger.error(f"开放API工单查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/workorders/create', methods=['POST'])
@openapi_auth
def openapi_workorder_create():
    """创建工单"""
    try:
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'error': _t('error.titleRequired', 'title不能为空')}), 400
        description = (data.get('description') or '').strip()
        priority = data.get('priority', 'normal')

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO workorders (org_id, title, description, priority, status, created_by) '
                'VALUES (?,?,?,?,?,?)',
                (g.org_id, title, description, priority, 'open', g.user_id)
            )
            wo_id = c.lastrowid
            conn.commit()
        log_action('openapi_workorder_create', 'workorder', wo_id,
                   detail={'title': title, 'priority': priority})
        return jsonify({'success': True, 'data': {'id': wo_id}})
    except Exception as e:
        logger.error(f"开放API创建工单失败: {e}")
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@open_api_bp.route('/openapi/v1/inspections/list', methods=['GET'])
@openapi_auth
def openapi_inspections_list():
    """查询巡检记录"""
    try:
        page, size, offset = parse_pagination()
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT COUNT(*) FROM inspection_records WHERE org_id=?',
                (g.org_id,)
            )
            total = c.fetchone()[0]
            c.execute(
                'SELECT id, plan_id, qrcode_id, asset_id, result, inspector_id, inspected_at '
                'FROM inspection_records WHERE org_id=? ORDER BY inspected_at DESC LIMIT ? OFFSET ?',
                (g.org_id, size, offset)
            )
            items = [_openapi_row_to_dict(r) for r in c.fetchall()]
        return jsonify({'success': True, 'data': {'items': items, 'total': total, 'page': page, 'size': size}})
    except Exception as e:
        logger.error(f"开放API巡检查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/stats/overview', methods=['GET'])
@openapi_auth
def openapi_stats_overview():
    """获取概览统计数据"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM qrcodes WHERE org_id=? AND is_deleted=0', (g.org_id,))
            qr_total = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM workorders WHERE org_id=?', (g.org_id,))
            wo_total = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM form_submissions fs JOIN forms f ON fs.form_id = f.id WHERE f.org_id=?', (g.org_id,))
            form_total = c.fetchone()[0]
            c.execute('SELECT COALESCE(SUM(scan_count),0) FROM qrcodes WHERE org_id=? AND is_deleted=0',
                      (g.org_id,))
            total_scans = c.fetchone()[0]
        return jsonify({'success': True, 'data': {
            'qrcodes_total': qr_total,
            'workorders_total': wo_total,
            'form_submissions_total': form_total,
            'total_scans': total_scans
        }})
    except Exception as e:
        logger.error(f"开放API统计查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/openapi/v1/token', methods=['POST'])
@openapi_auth
def openapi_issue_jwt():
    """签发JWT令牌（需先通过API Key认证）"""
    try:
        if g.auth_type != 'apikey':
            return jsonify({'error': _t('error.jwtRequiresApiKey', '签发JWT需要使用API Key认证')}), 400
        data = request.get_json(silent=True) or {}
        expire_minutes = min(360, max(1, int(data.get('expire_minutes', 60))))

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM openapps WHERE id=?', (g.app_id,))
            app = c.fetchone()
            if not app:
                return jsonify({'error': _t('error.appNotFound', '应用不存在')}), 404

        token = _openapi_generate_jwt(g.app_id, g.user_id, g.org_id, app['app_secret'], expire_minutes)
        return jsonify({'success': True, 'data': {
            'access_token': token,
            'expires_in': expire_minutes * 60,
            'token_type': 'Bearer'
        }})
    except Exception as e:
        logger.error(f"签发JWT失败: {e}")
        return jsonify({'error': _t('error.issueFailed', '签发失败')}), 500



@open_api_bp.route('/openapi/v1/token/revoke', methods=['POST'])
@openapi_auth
def openapi_revoke_token():
    """吊销当前JWT令牌"""
    try:
        if g.auth_type != 'jwt':
            return jsonify({'error': _t('error.jwtRevokeOnly')}), 400
        auth_header = request.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.startswith('Bearer ') else ''
        data = _openapi_verify_jwt(token, '')
        if data and data.get('jti'):
            with get_db() as conn:
                c = conn.cursor()
                c.execute('UPDATE openapps_tokens SET revoked=1 WHERE jti=?', (data['jti'],))
                conn.commit()
        return jsonify({'success': True, 'message': '令牌已吊销'})
    except Exception as e:
        logger.error(f"吊销令牌失败: {e}")
        return jsonify({'error': _t('error.revokeFailed', '吊销失败')}), 500


# ── OAuth2 端点 ──
# OAuth2 是一种授权协议，允许第三方应用在用户授权后访问用户数据
# 流程：第三方应用 → 用户授权 → 获取授权码 → 换取令牌 → 访问API


@open_api_bp.route('/oauth2/authorize', methods=['GET'])
@login_required
def oauth2_authorize():
    """OAuth2授权页面
    
    这是OAuth2授权流程的第一步：用户确认授权。
    第三方应用会将用户重定向到这个页面，展示授权确认界面。
    
    流程：
    1. 第三方应用携带 client_id、redirect_uri、scope 等参数跳转过来
    2. 系统验证 client_id 是否合法，redirect_uri 是否匹配
    3. 显示授权页面，让用户确认是否授权
    4. 用户确认后，生成授权码并发给第三方应用
    """
    client_id = request.args.get('client_id', '')
    redirect_uri = (request.args.get('redirect_uri') or '').strip()
    scope = (request.args.get('scope') or '').strip()
    response_type = request.args.get('response_type', 'code')

    if response_type != 'code':
        return jsonify({'error': _t('error.onlyAuthCodeSupported', '仅支持授权码模式(response_type=code)')}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM oauth2_clients WHERE client_id=? AND is_enabled=1', (client_id,))
        client = c.fetchone()
        if not client:
            return jsonify({'error': _t('error.invalidClientId', '无效的客户端ID')}), 400

        redirect_uris = (client['redirect_uris'] or '').strip().split('\n')
        if redirect_uri not in [r.strip() for r in redirect_uris if r.strip()]:
            return jsonify({'error': _t('error.redirectUriMismatch', 'redirect_uri不匹配')}), 400

    return render_template('oauth2_authorize.html',
                          client_name=client['client_name'],
                          client_id=client_id,
                          redirect_uri=redirect_uri,
                          scope=scope)



@open_api_bp.route('/oauth2/authorize/confirm', methods=['POST'])
@login_required
def oauth2_authorize_confirm():
    """确认授权 — 生成授权码
    
    用户点击"确认授权"按钮后，系统生成一个一次性的授权码（code），
    并将其包含在重定向URL中返回给第三方应用。
    
    授权码有效期10分钟，用完即删。
    """
    client_id = request.form.get('client_id', '')
    redirect_uri = (request.form.get('redirect_uri') or '').strip()
    scope = (request.form.get('scope') or '').strip()

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM oauth2_clients WHERE client_id=? AND is_enabled=1', (client_id,))
        client = c.fetchone()
        if not client:
            return jsonify({'error': _t('error.invalidClientId', '无效的客户端ID')}), 400

        code = secrets.token_urlsafe(32)
        expires_at = (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            'INSERT INTO oauth2_codes (client_id, user_id, code, scope, redirect_uri, expires_at) '
            'VALUES (?,?,?,?,?,?)',
            (client['id'], session['user_id'], code, scope, redirect_uri, expires_at)
        )
        conn.commit()

    sep = '&' if '?' in redirect_uri else '?'
    return redirect(f'{redirect_uri}{sep}code={code}&state={request.form.get("state", "")}')



@open_api_bp.route('/oauth2/token', methods=['POST'])
def oauth2_token():
    """OAuth2令牌签发
    
    第三方应用用授权码换取访问令牌（access_token）。
    支持两种grant_type：
    1. authorization_code：用授权码换令牌（首次获取）
    2. refresh_token：用刷新令牌换新令牌（令牌过期后刷新）
    """
    grant_type = request.form.get('grant_type', 'authorization_code')
    client_id = request.form.get('client_id', '')
    client_secret = request.form.get('client_secret', '')

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM oauth2_clients WHERE client_id=? AND is_enabled=1', (client_id,))
        client = c.fetchone()
        if not client or client['client_secret'] != client_secret:
            return jsonify({'error': 'invalid_client', 'error_description': '客户端凭证无效'}), 401

        if grant_type == 'authorization_code':
            code = request.form.get('code', '')
            redirect_uri = (request.form.get('redirect_uri') or '').strip()

            c.execute('SELECT * FROM oauth2_codes WHERE code=? AND expires_at > ?',
                      (code, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            auth_code = c.fetchone()
            if not auth_code or auth_code['client_id'] != client['id']:
                return jsonify({'error': 'invalid_grant', 'error_description': _t('error.invalidGrant')}), 400

            if redirect_uri and auth_code['redirect_uri'] != redirect_uri:
                return jsonify({'error': 'invalid_grant', 'error_description': _t('error.redirectUriMismatch')}), 400

            access_token = secrets.token_urlsafe(32)
            refresh_token = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')

            c.execute(
                'INSERT INTO oauth2_tokens (client_id, user_id, access_token, refresh_token, scope, expires_at) '
                'VALUES (?,?,?,?,?,?)',
                (client['id'], auth_code['user_id'], access_token, refresh_token, auth_code['scope'], expires_at)
            )
            c.execute('DELETE FROM oauth2_codes WHERE code=?', (code,))
            conn.commit()

            return jsonify({
                'access_token': access_token,
                'token_type': 'Bearer',
                'expires_in': 7200,
                'refresh_token': refresh_token,
                'scope': auth_code['scope']
            })

        elif grant_type == 'refresh_token':
            refresh_token = request.form.get('refresh_token', '')
            c.execute(
                'SELECT * FROM oauth2_tokens WHERE refresh_token=? AND client_id=?',
                (refresh_token, client['id'])
            )
            old_token = c.fetchone()
            if not old_token:
                return jsonify({'error': 'invalid_grant', 'error_description': _t('error.refreshToken')}), 400

            new_access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')

            c.execute(
                'UPDATE oauth2_tokens SET access_token=?, refresh_token=?, expires_at=? WHERE id=?',
                (new_access_token, new_refresh_token, expires_at, old_token['id'])
            )
            conn.commit()

            return jsonify({
                'access_token': new_access_token,
                'token_type': 'Bearer',
                'expires_in': 7200,
                'refresh_token': new_refresh_token,
                'scope': old_token['scope']
            })
        else:
            return jsonify({'error': 'unsupported_grant_type', 'error_description': _t('error.unsupportedGrantType', grant_type=grant_type)}), 400


# ── 开发者中心管理路由 ──


@open_api_bp.route('/api/openplatform/apps', methods=['GET'])
@require_permission('user:manage')
def api_openplatform_list_apps():
    """获取当前组织的应用列表"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id, app_name, app_description, app_key, ip_whitelist, rate_limit_qpm, is_enabled, created_at '
                'FROM openapps WHERE org_id=? ORDER BY created_at DESC',
                (org_id,)
            )
            apps = [_openapi_row_to_dict(r) for r in c.fetchall()]
        return jsonify({'success': True, 'data': {'apps': apps}})
    except Exception as e:
        logger.error(f"应用列表查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/api/openplatform/apps', methods=['POST'])
@require_permission('user:manage')
def api_openplatform_create_app():
    """创建应用"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        data = request.get_json(silent=True) or {}
        app_name = (data.get('app_name') or '').strip()
        if not app_name:
            return jsonify({'error': _t('error.appNameRequired', '应用名称不能为空')}), 400

        app_key = _openapi_generate_app_key()
        app_secret = _openapi_generate_secret()
        description = (data.get('app_description') or '').strip()
        ip_whitelist = (data.get('ip_whitelist') or '').strip()
        rate_limit_qpm = max(1, min(10000, int(data.get('rate_limit_qpm', 100) or 100)))

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO openapps (org_id, app_name, app_description, app_key, app_secret, ip_whitelist, rate_limit_qpm, created_by) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (org_id, app_name, description, app_key, app_secret, ip_whitelist, rate_limit_qpm, user_id)
            )
            app_id = c.lastrowid
            conn.commit()

        log_action('openplatform_app_create', 'openapp', app_id,
                   detail={'app_name': app_name, 'app_key': app_key})
        return jsonify({'success': True, 'data': {
            'id': app_id, 'app_key': app_key, 'app_secret': app_secret,
            'message': '应用创建成功！请妥善保管app_secret，仅显示一次。'
        }})
    except Exception as e:
        logger.error(f"创建应用失败: {e}")
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@open_api_bp.route('/api/openplatform/apps/<int:app_id>', methods=['PUT'])
@require_permission('user:manage')
def api_openplatform_update_app(app_id):
    """更新应用配置"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}

        updates = {}
        if 'app_name' in data:
            n = (data['app_name'] or '').strip()
            if not n:
                return jsonify({'error': _t('error.appNameRequired', '应用名称不能为空')}), 400
            updates['app_name'] = n
        if 'app_description' in data:
            updates['app_description'] = (data['app_description'] or '').strip()
        if 'ip_whitelist' in data:
            updates['ip_whitelist'] = (data['ip_whitelist'] or '').strip()
        if 'rate_limit_qpm' in data:
            updates['rate_limit_qpm'] = max(1, min(10000, int(data.get('rate_limit_qpm', 100) or 100)))
        if 'is_enabled' in data:
            updates['is_enabled'] = 1 if data['is_enabled'] else 0

        if not updates:
            return jsonify({'error': _t('error.noValidUpdateFields', '无有效更新字段')}), 400

        updates['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM openapps WHERE id=? AND org_id=?', (app_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.appNotFound', '应用不存在')}), 404

            set_clause = ', '.join(f'{k}=?' for k in updates)
            c.execute(
                f'UPDATE openapps SET {set_clause} WHERE id=? AND org_id=?',
                list(updates.values()) + [app_id, org_id]
            )
            conn.commit()

        log_action('openplatform_app_update', 'openapp', app_id, detail=updates)
        return jsonify({'success': True, 'data': updates})
    except Exception as e:
        logger.error(f"更新应用失败: {e}")
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500



@open_api_bp.route('/api/openplatform/apps/<int:app_id>/regenerate', methods=['POST'])
@require_permission('user:manage')
def api_openplatform_regenerate_secret(app_id):
    """重新生成密钥"""
    try:
        org_id = session.get('org_id')
        new_secret = _openapi_generate_secret()

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM openapps WHERE id=? AND org_id=?', (app_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.appNotFound', '应用不存在')}), 404

            c.execute('UPDATE openapps SET app_secret=?, updated_at=? WHERE id=? AND org_id=?',
                      (new_secret, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), app_id, org_id))
            conn.commit()

        log_action('openplatform_app_regenerate', 'openapp', app_id, detail={'regenerated': True})
        return jsonify({'success': True, 'data': {
            'app_secret': new_secret,
            'message': '密钥已重新生成，旧密钥立即失效。请妥善保管新密钥，仅显示一次。'
        }})
    except Exception as e:
        logger.error(f"重新生成密钥失败: {e}")
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500



@open_api_bp.route('/api/openplatform/apps/<int:app_id>/stats', methods=['GET'])
@require_permission('user:manage')
def api_openplatform_app_stats(app_id):
    """获取应用调用统计"""
    try:
        org_id = session.get('org_id')
        days = max(1, min(30, int(request.args.get('days', 7))))

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM openapps WHERE id=? AND org_id=?', (app_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.appNotFound', '应用不存在')}), 404

            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            c.execute(
                'SELECT DATE(created_at) as dt, COUNT(*) as cnt, '
                'SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) as success, '
                'SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as error '
                'FROM openapi_access_logs WHERE app_id=? AND created_at >= ? '
                'GROUP BY dt ORDER BY dt',
                (app_id, since)
            )
            daily_stats = [_openapi_row_to_dict(r) for r in c.fetchall()]

            c.execute(
                'SELECT path, COUNT(*) as cnt FROM openapi_access_logs '
                'WHERE app_id=? AND created_at >= ? GROUP BY path ORDER BY cnt DESC LIMIT 20',
                (app_id, since)
            )
            path_stats = [_openapi_row_to_dict(r) for r in c.fetchall()]

        return jsonify({'success': True, 'data': {
            'daily_stats': daily_stats,
            'path_stats': path_stats,
            'days': days
        }})
    except Exception as e:
        logger.error(f"应用统计查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@open_api_bp.route('/api/openplatform/apps/<int:app_id>/logs', methods=['GET'])
@require_permission('user:manage')
def api_openplatform_app_logs(app_id):
    """获取应用调用日志"""
    try:
        org_id = session.get('org_id')
        page, size, offset = parse_pagination(default_size=50, max_size=200)

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM openapps WHERE id=? AND org_id=?', (app_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.appNotFound')}), 404

            c.execute('SELECT COUNT(*) FROM openapi_access_logs WHERE app_id=?', (app_id,))
            total = c.fetchone()[0]

            c.execute(
                'SELECT id, method, path, status_code, error_message, request_ip, request_time, created_at '
                'FROM openapi_access_logs WHERE app_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?',
                (app_id, size, offset)
            )
            logs = [_openapi_row_to_dict(r) for r in c.fetchall()]

        return jsonify({'success': True, 'data': {
            'logs': logs, 'total': total, 'page': page, 'size': size,
            'total_pages': max(1, (total + size - 1) // size)
        }})
    except Exception as e:
        logger.error(f"应用日志查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


# ── 工作流引擎已迁移到 routes/workflow_engine.py ──


# ── 工作流管理API ──