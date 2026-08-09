"""
routes/shared.py - 共享模块
供各路由模块导入使用：数据库、认证、权限、工具函数等

这个文件是整个系统的"工具箱"，包含了所有常用的通用工具和配置：
- 数据库连接上下文管理器
- 认证和权限装饰器
- 二维码生成工具
- 通知发送（支持Webhook异步）
- 配额管理和订阅检查
- 版本管理和审计日志
- 批量操作工具
- 组织架构工具
"""

# ============ 导入依赖库 ============
# 标准库
import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import socket
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

# 第三方库
from flask import request, jsonify, session, redirect, g
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# qrcode 相关
import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer, SquareModuleDrawer
from qrcode.image.svg import SvgPathImage

# 后端国际化支持
from backend_i18n import t as _i18n_t, clear_cache as _i18n_clear_cache, get_locale as _i18n_get_locale

# ============ 常量定义 ============
# 分页默认值
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_SEARCH_PAGE_SIZE = 50
MAX_SEARCH_PAGE_SIZE = 200

# 超时设置（秒）
WEBHOOK_TIMEOUT = 5
WORKFLOW_WEBHOOK_TIMEOUT = 10

# 编码长度
SHORT_CODE_LENGTH = 6
SHORT_UUID_LENGTH = 8

# 工作流设置
DEFAULT_OVERDUE_HOURS = 24
SCHEDULE_POLL_INTERVAL = 300  # 5分钟


def _t(key, default=None, **params):
    """快捷翻译函数，用于路由中返回翻译后的消息
    如果翻译未找到则返回 default 或 key 本身
    
    参数：
        key: 翻译键（如 'auth.sessionExpired'）
        default: 当翻译未找到时使用的默认文本
        params: 动态参数，用于替换翻译文本中的占位符
    """
    result =_i18n_t(key, params=params if params else None)
    if result == key and default is not None:
        return default
    return result

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(module)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ============ 配置管理类 ============
class Config:
    """集中配置管理，优先从环境变量读取
    这样可以在不修改代码的情况下，通过环境变量改变配置
    适合不同环境（开发/测试/生产）的不同配置需求
    """
    SECRET_KEY = os.environ.get('SMARTCODE_SECRET_KEY') or secrets.token_hex(32)
    UPLOAD_FOLDER = os.environ.get('SMARTCODE_UPLOAD_FOLDER', 'uploads')
    DATABASE = os.environ.get('SMARTCODE_DATABASE', 'data/smartcode.db')
    MAX_FILE_SIZE = int(os.environ.get('SMARTCODE_MAX_FILE_SIZE', 500 * 1024 * 1024))
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

# 导出全局配置变量供其他模块使用
UPLOAD_FOLDER = Config.UPLOAD_FOLDER
DATABASE = Config.DATABASE
MAX_FILE_SIZE = Config.MAX_FILE_SIZE

# ============ 文件上传白名单 ============
# 按类别分组允许上传的文件扩展名
ALLOWED_EXTENSIONS = {
    'file': {'zip', 'doc', 'docx', 'pdf', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'},  # 文档类
    'image': {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'},  # 图片类
    'media': {'mp4', 'avi', 'mov', 'mkv', 'mp3', 'wav', 'flac', 'm4a'}  # 音视频类
}

# 合并所有允许的扩展名用于文件上传校验（去重）
_ALL_ALLOWED_EXTENSIONS = set().union(*ALLOWED_EXTENSIONS.values())

def _safe_t(key, fallback='服务器错误，请稍后重试'):
    """安全翻译函数，即使语言包加载失败也不会抛出异常
    用于错误处理中，确保始终能返回一个可阅读的错误消息
    """
    try:
        return _t(key, fallback)
    except Exception:
        return fallback


def _normalize_locale(locale):
    """规范化前端/后端传入的 locale 值
    处理各种格式如 'zh-CN' -> 'zh', 'en-US' -> 'en'
    只支持 zh/en/ja/ko 四种语言，其他默认使用中文
    """
    if not locale:
        return 'zh'
    code = str(locale).strip().lower().split('-')[0]  # 取语言代码的第一部分
    return code if code in {'zh', 'en', 'ja', 'ko'} else 'zh'


# ============ 装饰器：认证和权限 ============

def login_required(f):
    """统一认证装饰器，避免每个路由重复写认证检查
    如果用户未登录（session 中没有 user_id），直接返回 401 未登录错误
    如果已登录，继续执行目标路由函数
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
        return f(*args, **kwargs)
    return decorated


def login_required_page(f):
    """页面路由认证装饰器
    如果用户未登录，重定向到首页；已登录则继续执行
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/')
        return f(*args, **kwargs)
    return decorated


def parse_pagination(default_size=DEFAULT_PAGE_SIZE, max_size=MAX_PAGE_SIZE):
    """统一解析分页参数，避免各路由重复写
    从 URL 查询参数中解析 page 和 size，做边界校验
    返回 (当前页, 每页条数, 偏移量)
    
    参数：
        default_size: 默认每页条数
        max_size: 最大允许每页条数（防止一次性查出太多数据）
    """
    try:
        page = max(1, int(
            request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1  # 参数非法时默认第一页
    try:
        size = min(max_size, max(1, int(
            request.args.get('size', default_size))))
    except (ValueError, TypeError):
        size = default_size  # 参数非法时使用默认值
    offset = (page - 1) * size  # 计算 SQL 查询的偏移量
    return page, size, offset


# ============ 状态枚举常量 ============
# 将常用状态定义为常量，避免散落在各处的"魔法值"

class QRStatus:
    """二维码状态常量"""
    NORMAL   = 'normal'      # 正常
    DISABLED = 'disabled'    # 禁用
    EXPIRED  = 'expired'     # 过期
    ARCHIVED = 'archived'    # 归档
    DELETED  = 'deleted'     # 删除

class WorkOrderStatus:
    """工单状态常量"""
    OPEN       = 'open'        # 待处理
    PROCESSING = 'processing'  # 处理中
    RESOLVED   = 'resolved'    # 已解决
    CLOSED     = 'closed'      # 已关闭

class SubscriptionStatus:
    """订阅状态常量"""
    TRIAL     = 'trial'      # 试用
    ACTIVE    = 'active'    # 活跃
    CANCELLED = 'cancelled' # 已取消
    EXPIRED   = 'expired'   # 已过期

class ApprovalState:
    """审批状态常量"""
    NONE     = 'none'       # 无需审批
    PENDING  = 'pending'   # 待审批
    APPROVED = 'approved'  # 已通过
    REJECTED = 'rejected'  # 已拒绝


# ============ 权限系统 ============

# 角色定义：每个角色包含标签和权限列表
# '*' 表示拥有所有权限（超级管理员）
ROLES = {
    'super_admin': {
        'label': '超级管理员',
        'permissions': ['*']
    },
    'org_admin': {
        'label': '组织管理员',
        'permissions': [
            'qrcode:create', 'qrcode:edit', 'qrcode:delete', 'qrcode:view',
            'form:create', 'form:edit', 'form:delete', 'form:view',
            'stats:view', 'file:upload', 'file:delete', 'user:manage',
            'tag:manage', 'audit:view',
            'asset:manage', 'inspection:view', 'inspection:submit',
            'workorder:create', 'workorder:manage',
            'version:rollback', 'version:delete'
        ]
    },
    'operator': {
        'label': '运营',
        'permissions': [
            'qrcode:create', 'qrcode:edit', 'qrcode:view',
            'form:create', 'form:edit', 'form:view',
            'stats:view', 'file:upload', 'tag:manage',
            'asset:view', 'inspection:submit', 'inspection:view',
            'workorder:create', 'workorder:view', 'audit:view',
            'version:rollback'
        ]
    },
    'editor': {
        'label': '编辑',
        'permissions': [
            'qrcode:create', 'qrcode:view',
            'form:view', 'file:upload',
            'asset:view', 'inspection:submit', 'workorder:create'
        ]
    },
    'viewer': {
        'label': '查看者',
        'permissions': [
            'qrcode:view', 'form:view', 'stats:view',
            'asset:view', 'inspection:view', 'workorder:view', 'audit:view'
        ]
    }
}


def require_permission(permission):
    """权限检查装饰器
    使用方式：@require_permission('qrcode:create')
    如果用户角色没有对应权限，返回 403 权限不足错误
    
    参数：
        permission: 需要的权限键，如 'qrcode:create'
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
            role = session.get('role', 'viewer')  # 从 session 获取当前用户角色
            perms = ROLES.get(role, {}).get('permissions', [])  # 获取该角色的所有权限
            # 如果不是 '*'（所有权限）且目标权限不在列表中，拒绝访问
            if '*' not in perms and permission not in perms:
                return jsonify({'error': _t('auth.unauthorized', '权限不足')}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ============ 数据库工具 ============

@contextmanager
def get_db():
    """数据库连接上下文管理器，确保连接正确关闭
    使用 with 语句：
        with get_db() as conn:
            c = conn.cursor()
            c.execute(...)
    执行完后自动关闭连接，不会泄漏连接
    
    同时设置了 row_factory = sqlite3.Row，使得查询结果可以通过列名访问：
        row['id'] 而不是 row[0]，代码更易读
    """
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn  # 将连接返回给 with 语句
    finally:
        conn.close()  # 无论是否发生异常，最终都会关闭连接


# ============ 通用工具函数 ============

def generate_short_code(length=SHORT_CODE_LENGTH):
    """生成唯一短码
    用于活码短链接，在数据库中检查唯一性，如果重复就重试最多10次
    参数 length 决定短码长度，默认6位
    
    算法：从字母+数字中随机选择，去数据库查询是否已存在
    如果不存在直接返回，如果存在继续重试
    """
    import random, string
    chars = string.ascii_letters + string.digits
    for _ in range(10):
        code = ''.join(random.choices(chars, k=length))
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM dynamic_links WHERE short_code=?', (code,))
            if not c.fetchone():  # 数据库中不存在，说明唯一
                return code
    # 如果10次都冲突（概率极低），使用 secrets 生成8字符
    return secrets.token_urlsafe(8)[:length]

def parse_user_agent(ua_string):
    """解析 User-Agent 字符串，返回 (设备类型, 操作系统, 浏览器)
    用于扫码日志记录，方便统计用户设备分布
    """
    ua = ua_string or ''
    # 判断设备类型和操作系统
    if any(x in ua for x in ['iPhone', 'iPad']):
        device = 'mobile'
        os_name = 'iOS'
    elif 'Android' in ua:
        device = 'mobile'
        os_name = 'Android'
    elif 'Mobile' in ua:
        device = 'mobile'
        os_name = 'Other'
    elif 'Windows' in ua:
        device = 'desktop'
        os_name = 'Windows'
    elif 'Mac' in ua:
        device = 'desktop'
        os_name = 'Mac'
    else:
        device = 'desktop'
        os_name = 'Other'
    # 判断浏览器
    if 'Edg' in ua:
        browser = 'Edge'
    elif 'Chrome' in ua:
        browser = 'Chrome'
    elif 'Firefox' in ua:
        browser = 'Firefox'
    elif 'Safari' in ua:
        browser = 'Safari'
    else:
        browser = 'Other'
    return device, os_name, browser

def log_action(action, target_type=None, target_id=None, detail=None,
               before_data=None, after_data=None):
    """写入审计日志（兼容百万级，自动记录 user_agent）
    记录用户所有重要操作，用于安全审计和问题追踪
    即使写入失败也只记录日志不抛出异常，不影响主业务流程
    
    参数：
        action: 操作类型，如 'create_qrcode', 'delete_form'
        target_type: 操作目标类型，如 'qrcode', 'form'
        target_id: 目标ID
        detail: 操作详情（字典，会序列化为JSON）
        before_data: 操作前数据快照（用于回滚）
        after_data: 操作后数据快照
    """
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO audit_logs
                (org_id, user_id, action, target_type, target_id, resource_type, resource_id,
                 detail, before_data, after_data, ip, user_agent)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (session.get('org_id'),           # 当前组织ID
                 session.get('user_id'),           # 当前用户ID
                 action,
                 target_type, target_id,
                 target_type, target_id,
                 json.dumps(detail, ensure_ascii=False) if detail else None,
                 json.dumps(before_data, ensure_ascii=False) if before_data else None,
                 json.dumps(after_data, ensure_ascii=False) if after_data else None,
                 request.remote_addr,              # 客户端IP
                 request.headers.get('User-Agent', '')[:500]))  # 限制长度，避免过大
            conn.commit()
    except Exception as e:
        logger.error(f"审计日志写入失败: {e}")


# ============ 通知发送 ============

def send_notification(org_id, category, title, content=None, level='info', user_id=None,
                      link=None, source_type=None, source_id=None, skip_inapp=False):
    """统一通知发送（异步兼容）
    同时支持：
    1. 站内通知（写入数据库，前端轮询查询）
    2. Webhook 回调（异步发送，不阻塞主线程）
    
    参数：
        org_id: 组织ID
        category: 通知分类，匹配 Webhook 配置的事件过滤
        title: 通知标题
        content: 通知内容
        level: 级别：info/warning/error
        user_id: 接收用户ID，如果为 None 表示发给组织所有人
        link: 关联链接（点击后跳转到哪里）
        source_type: 来源类型
        source_id: 来源ID
        skip_inapp: 是否跳过站内通知（只发 Webhook）
    """
    try:
        with get_db() as conn:
            c = conn.cursor()

            # 写入站内通知（如果不跳过的话）
            if not skip_inapp:
                c.execute('''INSERT INTO notifications
                    (org_id, user_id, category, title, content, level, link, source_type, source_id)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (org_id, user_id, category, title, content, level, link, source_type, source_id))
                conn.commit()

            # 查询该组织所有启用的 Webhook 配置
            # 如果配置中包含 '*' 或者匹配当前分类，就发送
            webhook_configs = []
            c.execute('SELECT * FROM webhook_configs WHERE org_id=? AND is_active=1', (org_id,))
            for row in c.fetchall():
                events = json.loads(row['events'] or '[]')
                if '*' in events or category in events:
                    webhook_configs.append(dict(row))

            # 构造 Webhook 负载
            payload = {
                'org_id': org_id, 'category': category, 'title': title,
                'content': content, 'level': level, 'user_id': user_id,
                'timestamp': datetime.now().isoformat()
            }

            # 异步发送每个匹配的 Webhook（不阻塞当前请求）
            for webhook in webhook_configs:
                _send_webhook_async(webhook, payload)

        return True
    except Exception as e:
        logger.error(f"通知发送失败: {e}")
        return False


def _send_webhook_async(webhook, payload):
    """异步发送 Webhook（使用 threading 避免阻塞主线程）
    发送完成后更新 Webhook 配置的 last_triggered_at 字段
    """
    def _send():
        try:
            import urllib.request
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(
                webhook['url'],
                data=data,
                headers={'Content-Type': 'application/json', 'User-Agent': 'SmartCode-Webhook/2.0'},
                method='POST'
            )
            # 如果配置了密钥，添加签名头部
            if webhook.get('secret'):
                req.add_header('X-SmartCode-Signature', webhook['secret'])
            # 设置5秒超时，避免长时间挂起
            with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as _resp:
                pass  # 只需要发送请求，不关心响应体
            # 更新最后触发时间
            with get_db() as conn:
                conn.cursor().execute(
                    'UPDATE webhook_configs SET last_triggered_at=CURRENT_TIMESTAMP WHERE id=?',
                    (webhook['id'],))
                conn.commit()
        except Exception as e:
            logger.error(f"Webhook 发送失败 {webhook['url']}: {e}")
    # 使用守护线程，主线程退出时自动结束
    threading.Thread(target=_send, daemon=True).start()


# ============ 二维码工具函数 ============

def validate_file_extension(filename):
    """校验文件扩展名是否在允许的白名单中
    防止上传恶意文件（如 .exe, .php 等）
    """
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in _ALL_ALLOWED_EXTENSIONS

def safe_filename(filename):
    """安全处理文件名，防止路径穿越攻击
    使用 werkzeug 的 secure_filename 保证安全
    """
    safe = secure_filename(filename or 'file')
    if not safe:
        safe = 'file'
    return safe

def generate_qrcode(data, config):
    """生成二维码图像，使用 fit=True 自动调整版本号以适配数据长度
    
    参数：
        data: 二维码内容字符串
        config: 配置字典，包含：
            error_correction: 纠错级别 L/M/Q/H (默认 M)
            box_size: 每个方块的像素大小 (默认 10)
            border: 边框大小 (默认 4)
            fill_color: 前景色 (默认 #000000)
            back_color: 背景色 (默认 #FFFFFF)
            style: 方块样式 'rounded' 圆角 / 默认方形
    
    返回：PIL Image 对象
    """
    # 纠错级别映射：L(7%) M(15%) Q(25%) H(30%)
    # 纠错级别越高，二维码容量越大，越容易扫码识别
    error_level = (config.get('error_correction', 'M') or 'M').upper()
    error_map = {
        'L': ERROR_CORRECT_L,
        'M': ERROR_CORRECT_M,
        'Q': ERROR_CORRECT_Q,
        'H': ERROR_CORRECT_H
    }
    error_correction = error_map.get(error_level, ERROR_CORRECT_M)

    # 创建 QRCode 对象，version=None 表示自动适配
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=config.get('box_size', 10),
        border=config.get('border', 4),
    )
    qr.add_data(data)
    qr.make(fit=True)  # fit=True 自动调整版本号
    
    # 获取样式配置
    fill_color = config.get('fill_color', '#000000')
    back_color = config.get('back_color', '#FFFFFF')
    
    # 选择方块绘制器：圆角或方形
    module_drawer = RoundedModuleDrawer() if config.get('style') == 'rounded' else SquareModuleDrawer()
    
    # 生成图像
    img = qr.make_image(
        fill_color=fill_color,
        back_color=back_color,
        module_drawer=module_drawer
    )

    # 处理特殊情况，确保返回 PIL Image 对象
    if hasattr(img, 'get_image'):
        img = img.get_image()
    buffer = io.BytesIO()
    img.save(buffer, 'PNG')
    buffer.seek(0)
    img = Image.open(buffer)
    img = img.convert('RGB')
    
    return img


def generate_svg(data, config):
    """生成 SVG 格式二维码（矢量图，可无限放大不失真）
    参数同 generate_qrcode
    返回：SVG XML 字符串
    """
    error_level = (config.get('error_correction', 'M') or 'M').upper()
    error_map = {
        'L': ERROR_CORRECT_L,
        'M': ERROR_CORRECT_M,
        'Q': ERROR_CORRECT_Q,
        'H': ERROR_CORRECT_H
    }
    error_correction = error_map.get(error_level, ERROR_CORRECT_M)

    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=config.get('box_size', 10),
        border=config.get('border', 4),
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(image_factory=SvgPathImage)
    return img.to_string().decode('utf-8')


def format_qrcode_payload(content, qtype='text'):
    """根据二维码类型格式化内容
    不同类型的二维码有不同的标准格式：
    - url: 直接返回字符串
    - email: 格式化为 mailto: URL
    - vcard: 格式化为 VCARD 标准格式
    - wifi: 格式化为 WiFi 连接标准格式
    """
    if qtype == 'url':
        return str(content or '')
    if qtype == 'email':
        email = ''
        subject = ''
        body = ''
        if isinstance(content, dict):
            email = content.get('email', '')
            subject = content.get('subject', '')
            body = content.get('body', '')
        # 使用 URL 编码编码 subject 和 body
        return f"mailto:{email.strip()}?subject={quote(subject)}&body={quote(body)}" if email else ''
    if qtype == 'vcard':
        name = ''
        phone = ''
        email = ''
        company = ''
        title = ''
        if isinstance(content, dict):
            name = content.get('name', '')
            phone = content.get('phone', '')
            email = content.get('email', '')
            company = content.get('company', '')
            title = content.get('title', '')
        # VCARD 3.0 标准格式
        vcard = [
            'BEGIN:VCARD',
            'VERSION:3.0',
            f'N:{name}',
            f'FN:{name}',
            f'ORG:{company}',
            f'TITLE:{title}',
            f'TEL:{phone}',
            f'EMAIL:{email}',
            'END:VCARD'
        ]
        # 过滤掉空行
        return '\n'.join([line for line in vcard if ':' in line and line.split(':', 1)[1].strip()])
    if qtype == 'wifi':
        ssid = ''
        password = ''
        security = 'WPA'
        if isinstance(content, dict):
            ssid = content.get('ssid', '')
            password = content.get('password', '')
            security = content.get('security', 'WPA')
        # WiFi 二维码标准格式：WIFI:T:{security};S:{ssid};P:{password};;
        return f"WIFI:T:{security};S:{ssid};P:{password};H:false;;" if ssid else ''
    return str(content or '')


def image_to_base64(img):
    """将 PIL Image 转换为 Base64 编码的 PNG 数据
    用于直接嵌入到 HTML 中显示，无需单独请求
    """
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def get_lan_ip():
    """获取本机局域网 IP 地址
    用于启动时显示可访问的地址
    原理：连接一个公网地址（8.8.8.8），然后获取本机使用的出口 IP
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# ============ 订阅与配额 ============

def get_org_subscription(org_id):
    """获取组织当前订阅信息
    返回最新的一条订阅记录（按 ID 降序取第一条）
    同时 JOIN 套餐表获取套餐信息
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''SELECT s.*, p.plan_key, p.name as plan_name, p.monthly_price, p.yearly_price,
                    p.features_json, p.quotas_json, p.description as plan_desc
                    FROM subscriptions s
                    JOIN plan_tiers p ON s.plan_id = p.id
                    WHERE s.org_id=? ORDER BY s.id DESC LIMIT 1''', (org_id,))
        return c.fetchone()


def get_org_quota(org_id, quota_key):
    """获取组织某项配额的使用量
    返回：当前使用量，如果没有记录返回 0
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT current_value FROM quota_usage WHERE org_id=? AND quota_key=?', (org_id, quota_key))
        row = c.fetchone()
        return row['current_value'] if row else 0


def update_org_quota(org_id, quota_key, delta):
    """更新配额使用量
    delta 为正表示增加使用量，为负表示减少使用量
    使用 ON CONFLICT 语法实现插入或更新（upsert）
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO quota_usage (org_id, quota_key, current_value, updated_at)
                    VALUES (?,?,?,CURRENT_TIMESTAMP)
                    ON CONFLICT(org_id, quota_key) DO UPDATE SET
                    current_value = current_value + ?, updated_at = CURRENT_TIMESTAMP''',
                 (org_id, quota_key, delta, delta))
        conn.commit()


def check_quota(org_id, quota_key, current_count=None):
    """检查配额是否超限
    返回：(是否可继续操作, 配额上限, 已用量, 超出提示)
    如果上限是 -1 表示无限制，直接返回 True
    """
    sub = get_org_subscription(org_id)
    if not sub:
        return True, 0, 0, ''  # 没有订阅信息，默认允许
    quotas = json.loads(sub['quotas_json'] or '{}')
    limit = quotas.get(quota_key, -1)
    if limit == -1:
        return True, -1, 0, ''  # 无限制
    # 如果调用者已经提供了当前数量，就不用再查数据库
    used = current_count if current_count is not None else get_org_quota(org_id, quota_key)
    if used >= limit:
        plan_name = sub['plan_name']
        return False, limit, used, f'当前套餐（{plan_name}）的{quota_key}配额已用完（{used}/{limit}），请升级套餐'
    return True, limit, used, ''


# ============ 版本管理 ============

def _insert_version(c, org_id, resource_type, resource_id, snapshot, content_hash, user_id, remark):
    """插入版本记录（内部辅助函数）"""
    c.execute('SELECT MAX(version) FROM resource_versions WHERE org_id=? AND resource_type=? AND resource_id=?',
             (org_id, resource_type, resource_id))
    max_ver = c.fetchone()[0] or 0
    c.execute('''INSERT INTO resource_versions
                (org_id, resource_type, resource_id, version, snapshot, content_hash, operator, remark)
                VALUES (?,?,?,?,?,?,?,?)''',
             (org_id, resource_type, resource_id, max_ver + 1, snapshot, content_hash, user_id, remark))


def save_version(resource_type, resource_id, snapshot, operator=None, remark=None, conn=None):
    """保存资源版本快照
    支持版本回滚功能，每次修改资源都会保存一个快照
    如果用户改错了，可以恢复到之前的版本
    
    参数：
        resource_type: 资源类型（如 'qrcode', 'form'）
        resource_id: 资源ID
        snapshot: 快照 JSON 字符串
        operator: 操作者ID，默认使用当前 session 用户
        remark: 版本备注
        conn: 外部传入的连接（用于事务，可选）
    """
    try:
        org_id = session.get('org_id')
        user_id = operator or session.get('user_id')
        content_hash = hashlib.md5(snapshot.encode('utf-8')).hexdigest()

        if conn:
            _insert_version(conn.cursor(), org_id, resource_type, resource_id, snapshot, content_hash, user_id, remark)
        else:
            with get_db() as db:
                _insert_version(db.cursor(), org_id, resource_type, resource_id, snapshot, content_hash, user_id, remark)
                db.commit()
        return True
    except Exception as e:
        logger.error(f"保存版本失败 {resource_type}#{resource_id}: {e}")
        return False


# ============ 生命周期状态机 ============
# 支持资源的完整生命周期：草稿 -> 审核 -> 发布 -> 运行 -> 暂停/过期 -> 归档/删除

LIFECYCLE_TRANSITIONS = {
    'draft':     ['reviewing', 'deleted'],    # 草稿可以提交审核或删除
    'reviewing': ['published', 'deleted'],    # 审核中可以发布或删除
    'published': ['running'],                 # 已发布进入运行中
    'running':   ['paused', 'expired', 'deleted'],  # 运行中可以暂停、标记过期、删除
    'paused':    ['running', 'deleted'],      # 暂停可以恢复运行或删除
    'expired':   ['archived', 'deleted'],     # 过期可以归档或删除
    'archived':  [],                          # 归档后不能再修改
    'deleted':   []                           # 删除后不能再修改
}

# 状态中文标签
LIFECYCLE_LABELS = {
    'draft': '草稿', 'reviewing': '审核中', 'published': '已发布',
    'running': '运行中', 'paused': '已暂停', 'expired': '已失效',
    'archived': '已归档', 'deleted': '已删除'
}

# 状态对应颜色（前端展示用）
LIFECYCLE_COLORS = {
    'draft': '#94A3B8', 'reviewing': '#F59E0B', 'published': '#1677FF',
    'running': '#22C55E', 'paused': '#F59E0B', 'expired': '#EF4444',
    'archived': '#6B7280', 'deleted': '#DC2626'
}


def validate_transition(current_status, target_status):
    """校验状态流转是否合法，基于预定义的状态机
    返回：(是否合法, 错误信息)
    
    业务意义：不允许非法的状态跳转，比如不能从"已删除"跳回"运行中"
    """
    if current_status not in LIFECYCLE_TRANSITIONS:
        return False, f'未知的当前状态: {current_status}'
    if target_status not in LIFECYCLE_TRANSITIONS:
        return False, f'未知的目标状态: {target_status}'
    if target_status not in LIFECYCLE_TRANSITIONS[current_status]:
        return False, f'不允许从 {LIFECYCLE_LABELS.get(current_status)} 切换到 {LIFECYCLE_LABELS.get(target_status)}'
    return True, ''


# ============ 工作流触发器 ============

def workflow_trigger_after_scan(qrcode_id, org_id, scan_count):
    """扫码后触发工作流
    延迟导入 WorkflowEngine 避免循环引用问题
    如果工作流模块未加载，静默失败不影响扫码
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT title FROM qrcodes WHERE id=?', (qrcode_id,))
        qr = c.fetchone()
    # 构造事件数据
    event = {
        'qrcode_id': qrcode_id,
        'qrcode_title': qr['title'] if qr else '',
        'scan_count': scan_count,
        'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    try:
        from routes.workflow_engine import WorkflowEngine
        WorkflowEngine.trigger_event(org_id, 'qrcode:scan', event)
    except ImportError:
        pass  # 如果导入失败（模块不存在），静默跳过


def workflow_trigger_after_qrcode_create(qrcode_id, org_id, title, created_by):
    """创建二维码后触发工作流"""
    event = {
        'qrcode_id': qrcode_id,
        'qrcode_title': title or '',
        'created_by': created_by,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    try:
        from routes.workflow_engine import WorkflowEngine
        WorkflowEngine.trigger_event(org_id, 'qrcode:created', event)
    except ImportError:
        pass


# ============ 组织架构工具 ============

# 节点类型中文标签
NODE_TYPES = {
    'department': '部门',
    'team': '团队',
    'position': '岗位',
    'virtual': '虚拟组织',
}


def _build_org_tree(rows):
    """将扁平的行数据构建为组织树结构
    输入：数据库查询出的所有部门行
    输出：嵌套的树形结构（包含 children 数组）
    
    算法：
    1. 将所有节点存入字典（id -> 节点）
    2. 遍历每个节点，根据 parent_id 找到父节点，将自己加入父节点的 children 列表
    3. 没有父节点的就是顶级节点，加入结果列表返回
    """
    if not rows:
        return []
    nodes = [dict(r) for r in rows]
    node_map = {n['id']: n for n in nodes}
    for n in nodes:
        n['children'] = []  # 预初始化 children 数组
    tree = []
    for n in nodes:
        parent_id = n.get('parent_id')
        if parent_id and parent_id in node_map:
            node_map[parent_id]['children'].append(n)
        else:
            tree.append(n)  # 没有父节点，加入顶级列表
    return tree


# ============ 批量操作与回收站 ============
# 支持批量删除、批量修改、批量启停等操作，异步执行，支持回滚

# 可批量操作的资源类型配置
RECYCLE_RESOURCES = {
    'qrcode': {'table': 'qrcodes', 'title_field': 'title', 'has_name': False},
    'form': {'table': 'forms', 'title_field': 'form_name', 'has_name': True},
    'file': {'table': 'files', 'title_field': 'name', 'has_name': False},
    'workorder': {'table': 'workorders', 'title_field': 'title', 'has_name': False},
    'inspection': {'table': 'inspection_plans', 'title_field': "('巡检计划 #' || id)", 'has_name': True}
}

# 资源类型对应表名映射
BATCH_RESOURCE_TABLES = {
    'qrcode': 'qrcodes',
    'file': 'files',
    'form': 'forms',
    'workorder': 'workorders',
    'inspection': 'inspection_records',
}

# 支持的批量操作类型
BATCH_ACTIONS = {
    'delete': {'label': '删除', 'icon': '🗑', 'color': '#EF4444', 'reversible': True},
    'modify': {'label': '修改', 'icon': '✏', 'color': '#F59E0B', 'reversible': True},
    'toggle': {'label': '启停', 'icon': '🔘', 'color': '#22C55E', 'reversible': True},
    'export': {'label': '导出', 'icon': '📥', 'color': '#6366F1', 'reversible': False},
    'tag': {'label': '标签', 'icon': '🏷', 'color': '#8B5CF6', 'reversible': True},
    'permission': {'label': '权限', 'icon': '🔒', 'color': '#EC4899', 'reversible': True},
    'archive': {'label': '归档', 'icon': '📁', 'color': '#6B7280', 'reversible': True},
}

# 批量执行器注册表和活动任务跟踪
BATCH_EXECUTORS = {}
ACTIVE_BATCH_TASKS = {}


def _batch_audit(org_id, user_id, task_id, action, resource_type, resource_id, detail=''):
    """记录批量操作审计日志"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO batch_audit_log (org_id, user_id, task_id, action, resource_type, resource_id, detail)
                        VALUES (?,?,?,?,?,?,?)''',
                     (org_id, user_id, task_id, action, resource_type, resource_id, detail))
            conn.commit()
    except Exception:
        pass


def _snapshot_resource(resource_type, resource_id):
    """获取资源快照（用于回滚）
    如果操作可逆，在修改前保存当前状态，出错时可以恢复
    """
    table = BATCH_RESOURCE_TABLES.get(resource_type)
    if not table:
        return None
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(f'SELECT * FROM {table} WHERE id=?', (resource_id,))
            row = c.fetchone()
            if row:
                return {k: row[k] for k in row.keys()}
    except Exception:
        pass
    return None


def _execute_batch_task(task_id):
    """异步执行批量任务
    从数据库读取任务信息，逐个处理资源，更新进度
    每个资源操作前保存快照，支持后续回滚
    """
    task_info = None
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM batch_tasks WHERE id=?', (task_id,))
            row = c.fetchone()
            if not row or row['status'] == 'cancelled':
                return
            task_info = dict(row)
            # 更新状态为 running
            c.execute('UPDATE batch_tasks SET status=?, started_at=? WHERE id=?',
                     ('running', datetime.now(), task_id))
            conn.commit()

        # 解析任务参数
        resource_type = task_info['resource_type']
        task_type = task_info['task_type']
        params = json.loads(task_info['params_json'] or '{}')
        resource_ids = params.get('resource_ids', [])

        if not resource_ids:
            with get_db() as conn:
                c = conn.cursor()
                c.execute('UPDATE batch_tasks SET status=?, error_msg=?, completed_at=? WHERE id=?',
                         ('failed', '没有选中任何资源', datetime.now(), task_id))
                conn.commit()
            return

        # 更新总数
        total = len(resource_ids)
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE batch_tasks SET total_count=? WHERE id=?', (total, task_id))
            conn.commit()

        # 逐个处理每个资源
        for i, rid in enumerate(resource_ids):
            # 如果任务已取消，提前退出
            if task_id in ACTIVE_BATCH_TASKS and ACTIVE_BATCH_TASKS[task_id].get('cancelled'):
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute('UPDATE batch_tasks SET status=? WHERE id=?', ('cancelled', task_id))
                    conn.commit()
                return

            # 如果操作可逆，先保存快照
            snapshot = _snapshot_resource(resource_type, rid) if BATCH_ACTIONS.get(task_type, {}).get('reversible') else None
            item_status = 'success'
            error_msg = ''

            try:
                # 执行操作
                _apply_batch_action(resource_type, task_type, rid, params)
            except Exception as e:
                error_msg = str(e)
                item_status = 'failed'
                # 自动重试最多3次
                if params.get('retry_count', 0) < params.get('max_retries', 3):
                    for attempt in range(params.get('max_retries', 3)):
                        try:
                            _apply_batch_action(resource_type, task_type, rid, params)
                            item_status = 'success'
                            error_msg = ''
                            break
                        except Exception as re:
                            error_msg = str(re)

            # 获取资源标题用于展示
            resource_title = snapshot.get('title') or snapshot.get('name') or snapshot.get('form_name') or str(rid) if snapshot else str(rid)

            # 记录任务项结果
            with get_db() as conn:
                c = conn.cursor()
                c.execute('''INSERT INTO batch_task_items (task_id, resource_id, resource_type, title, action, status, error_msg, snapshot_json, processed_at)
                            VALUES (?,?,?,?,?,?,?,?,?)''',
                         (task_id, rid, resource_type, resource_title, task_type, item_status,
                          error_msg, json.dumps(snapshot) if snapshot else None, datetime.now()))
                conn.commit()

            # 记录审计日志
            _batch_audit(task_info['org_id'], task_info['user_id'], task_id, task_type, resource_type, rid,
                        f'批量{task_type}: {resource_title} - {item_status}')

            # 更新成功/失败计数
            success_inc = 1 if item_status == 'success' else 0
            fail_inc = 1 if item_status == 'failed' else 0
            with get_db() as conn:
                c = conn.cursor()
                c.execute('''UPDATE batch_tasks SET success_count=success_count+?, fail_count=fail_count+?
                            WHERE id=?''', (success_inc, fail_inc, task_id))
                conn.commit()

        # 全部完成，标记为 completed
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE batch_tasks SET status=?, completed_at=? WHERE id=?',
                     ('completed', datetime.now(), task_id))
            conn.commit()

    except Exception as e:
        logger.error(f"批量任务执行失败: {e}", exc_info=True)
        if task_id:
            with get_db() as conn:
                c = conn.cursor()
                c.execute('UPDATE batch_tasks SET status=?, error_msg=?, completed_at=? WHERE id=?',
                         ('failed', str(e), datetime.now(), task_id))
                conn.commit()


def _apply_batch_action(resource_type, task_type, resource_id, params):
    """执行单个批量操作
    根据操作类型执行不同的 SQL 更新
    """
    table = BATCH_RESOURCE_TABLES.get(resource_type)
    if not table:
        raise ValueError(f'未知资源类型: {resource_type}')

    with get_db() as conn:
        c = conn.cursor()

        if task_type == 'delete':
            # 删除：软删除，设置 is_active=0
            c.execute(f'UPDATE {table} SET is_active=0 WHERE id=?', (resource_id,))
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'modify':
            # 修改：批量更新指定字段
            updates = params.get('updates', {})
            if not updates:
                raise ValueError('没有修改内容')
            # 构造 SET 子句：field1=?, field2=?
            set_clause = ', '.join([f'{k}=?' for k in updates])
            values = list(updates.values()) + [resource_id]
            c.execute(f'UPDATE {table} SET {set_clause} WHERE id=?', values)
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'toggle':
            # 启停：批量切换激活状态
            new_state = params.get('target_state', 1)
            c.execute(f'UPDATE {table} SET is_active=? WHERE id=?', (new_state, resource_id))
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'tag':
            # 修改标签
            tag_value = params.get('tag', '')
            c.execute(f'UPDATE {table} SET tags=? WHERE id=?', (tag_value, resource_id))
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'permission':
            # 修改权限（只支持文件）
            new_permission = params.get('permission', '')
            if table == 'files':
                c.execute(f'UPDATE {table} SET description=? WHERE id=?', (f'[权限:{new_permission}]', resource_id))
            else:
                raise ValueError('该资源类型不支持权限操作')

        elif task_type == 'archive':
            # 归档：设置对应状态
            if table == 'qrcodes':
                c.execute(f'UPDATE {table} SET current_status=? WHERE id=?', ('archived', resource_id))
            elif table == 'workorders':
                c.execute(f'UPDATE {table} SET status=? WHERE id=?', ('closed', resource_id))
            elif table == 'forms':
                c.execute(f'UPDATE {table} SET status=? WHERE id=?', ('archived', resource_id))
            else:
                raise ValueError('该资源类型不支持归档操作')

        elif task_type == 'export':
            # 导出在任务创建时已经处理，这里不需要做什么
            pass

        else:
            raise ValueError(f'未知操作类型: {task_type}')

        conn.commit()


def _rollback_batch_task(task_id):
    """回滚批量任务
    遍历所有成功的任务项，使用之前保存的快照恢复数据
    只有可逆操作才能回滚
    """
    try:
        with get_db() as conn:
            c = conn.cursor()
            # 查询所有成功且有快照的任务项
            c.execute('SELECT * FROM batch_task_items WHERE task_id=? AND status=? AND snapshot_json IS NOT NULL',
                     (task_id, 'success'))
            items = c.fetchall()

        rolled = 0
        failed = 0
        for item in items:
            try:
                snapshot = json.loads(item['snapshot_json'])
                resource_type = item['resource_type']
                table = BATCH_RESOURCE_TABLES.get(resource_type)
                if not table or not snapshot:
                    continue

                snapshot_id = snapshot.pop('id', None)
                if not snapshot_id:
                    continue

                # 过滤掉非字段项（如外键注释）
                snapshot = {k: v for k, v in snapshot.items() if not k.startswith('FOREIGN')}

                # 使用快照所有字段覆盖当前记录，恢复到修改前
                with get_db() as conn:
                    c = conn.cursor()
                    set_clause = ', '.join([f'{k}=?' for k in snapshot])
                    values = list(snapshot.values()) + [snapshot_id]
                    c.execute(f'UPDATE {table} SET {set_clause} WHERE id=?', values)
                    conn.commit()

                # 标记为已回滚
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute('UPDATE batch_task_items SET status=? WHERE id=?', ('rolled_back', item['id']))
                    conn.commit()
                rolled += 1
            except Exception as e:
                logger.error(f"回滚任务项失败: {e}")
                failed += 1

        # 更新任务状态为已回滚
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE batch_tasks SET status=? WHERE id=?', ('rolled_back', task_id))
            conn.commit()

        return rolled, failed
    except Exception as e:
        logger.error(f"回滚失败: {e}", exc_info=True)
        return 0, 0


# ============ 权限常量列表 ============
# 导出所有可用权限键，前端用于配置界面
PERMISSION_KEYS = sorted({
    'qrcode:create', 'qrcode:edit', 'qrcode:delete', 'qrcode:view',
    'form:create', 'form:edit', 'form:delete', 'form:view',
    'stats:view', 'file:upload', 'file:delete', 'user:manage',
    'tag:manage', 'audit:view',
    'asset:manage', 'asset:view',
    'inspection:view', 'inspection:submit',
    'workorder:create', 'workorder:manage', 'workorder:view',
    'version:rollback', 'version:delete'
})


# ============ 组织架构子树重算 ============

def _recalc_subtree(conn, dept_id, org_id, new_parent_path, new_depth):
    """移动节点后重新计算该节点及其所有子节点的路径和深度
    当一个部门被移动到另一个父部门下，需要更新该部门及其所有后代的路径信息
    
    参数：
        conn: 数据库连接
        dept_id: 当前节点ID
        org_id: 组织ID
        new_parent_path: 新父节点的完整路径
        new_depth: 新深度
    """
    c = conn.cursor()
    c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
              (dept_id, org_id))
    node = c.fetchone()
    if not node:
        return
    old_path = node['path']
    depth_diff = new_depth - node['depth']
    # 更新当前节点
    new_node_path = new_parent_path + str(dept_id) + '/'
    c.execute('UPDATE departments SET path=?, depth=? WHERE id=?',
              (new_node_path, new_depth, dept_id))
    # 递归更新所有子节点（使用 LIKE 查询找出所有后代）
    c.execute(
        'SELECT * FROM departments WHERE org_id=? AND is_deleted=0 AND path LIKE ? AND id != ?',
        (org_id, old_path + '%', dept_id)
    )
    children = c.fetchall()
    for child in children:
        # 新路径 = 新父路径 + 原路径中从旧父路径之后的部分
        new_child_path = new_node_path + child['path'][len(old_path):]
        c.execute('UPDATE departments SET path=?, depth=depth+? WHERE id=?',
                  (new_child_path, depth_diff, child['id']))


# ============ 部门成员计数同步 ============

def _sync_member_count(conn, dept_id, org_id):
    """同步部门成员数量冗余字段
    统计该部门当前有多少成员，更新到 departments.member_count
    这是一个冗余优化，避免每次显示都要 COUNT
    """
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM department_users WHERE department_id=? AND org_id=?',
              (dept_id, org_id))
    count = c.fetchone()[0]
    c.execute('UPDATE departments SET member_count=? WHERE id=? AND org_id=?',
              (count, dept_id, org_id))


def generate_asset_code():
    """生成资产编码，格式：ASSET-年份-四位序号"""
    from datetime import datetime
    year = datetime.now().year
    with get_db() as conn:
        c = conn.cursor()
        try:
            c.execute(
                'SELECT COUNT(*) FROM assets '
                'WHERE asset_code LIKE ?',
                (f'ASSET-{year}-%',))
            count = c.fetchone()[0] + 1
        except Exception:
            count = 1
    return f'ASSET-{year}-{count:04d}'


def generate_short_uuid(length=SHORT_UUID_LENGTH):
    """生成指定长度的短UUID"""
    import uuid as _uuid
    return str(_uuid.uuid4()).replace(
        '-', '')[:length]


def workflow_trigger_after_inspection(
        org_id, qrcode_id, result,
        inspector_id, record_id):
    """巡检完成后触发工作流（占位实现）"""
    try:
        log_action(
            'workflow_trigger',
            'inspection_record',
            record_id,
            {
                'trigger': 'after_inspection',
                'org_id': org_id,
                'qrcode_id': qrcode_id,
                'result': result
            }
        )
    except Exception as e:
        logger.error(f"巡检工作流触发失败: {e}")


def workflow_trigger_after_workorder_status(
        org_id, workorder_id,
        old_status, new_status, operator_id):
    """工单状态变更后触发工作流（占位实现）"""
    try:
        log_action(
            'workflow_trigger',
            'workorder',
            workorder_id,
            {
                'trigger': 'after_status_change',
                'org_id': org_id,
                'old_status': old_status,
                'new_status': new_status
            }
        )
    except Exception as e:
        logger.error(f"工单状态工作流触发失败: {e}")


NOTIFICATION_CATEGORIES = {
    'system':     '系统通知',
    'workorder':  '工单通知',
    'inspection': '巡检通知',
    'qrcode':     '二维码通知',
    'approval':   '审批通知',
    'workflow':   '工作流通知'
}

NOTIFICATION_LEVELS = {
    'info':    '普通',
    'warning': '警告',
    'error':   '错误',
    'success': '成功'
}

DEFAULT_NOTIFICATION_SETTINGS = {
    'inapp_enabled':     1,
    'email_enabled':     0,
    'webhook_enabled':   0,
    'webhook_url':       '',
    'notify_system':     1,
    'notify_workorder':  1,
    'notify_inspection': 1,
    'notify_qrcode':     1,
    'notify_approval':   1,
    'notify_workflow':   1
}


SEARCHABLE_RESOURCES = {
    'qrcode': {
        'table':       'qrcodes',
        'title_field': 'title',
        'label':       '二维码'
    },
    'form': {
        'table':       'forms',
        'title_field': 'form_name',
        'label':       '表单'
    },
    'workorder': {
        'table':       'workorders',
        'title_field': 'title',
        'label':       '工单'
    },
    'asset': {
        'table':       'assets',
        'title_field': 'name',
        'label':       '资产'
    },
    'file': {
        'table':       'files',
        'title_field': 'original_name',
        'label':       '文件'
    }
}


# ============ 登录速率限制 ============
# 基于IP的登录失败计数，防止暴力破解
# 结构: {ip: {'count': int, 'first_attempt': datetime, 'blocked_until': datetime}}
_login_attempts = {}
_LOGIN_MAX_ATTEMPTS = 5       # 最大失败次数
_LOGIN_WINDOW_SECONDS = 60    # 计数窗口（秒）
_LOGIN_BLOCK_SECONDS = 900    # 封禁时长（秒，默认15分钟）


def check_login_rate_limit(ip):
    """检查登录速率限制
    
    返回: (is_allowed: bool, remaining: int, message: str)
    - is_allowed: 是否允许尝试
    - remaining: 剩余尝试次数
    - message: 错误信息（仅当 is_allowed=False 时有效）
    """
    now = datetime.now()
    record = _login_attempts.get(ip)

    if record:
        # 检查是否在封禁期内
        if record.get('blocked_until') and now < record['blocked_until']:
            wait_seconds = int((record['blocked_until'] - now).total_seconds())
            return False, 0, f'登录尝试次数过多，请{wait_seconds}秒后再试'

        # 检查是否超出时间窗口，如果是则重置计数
        if (now - record['first_attempt']).total_seconds() > _LOGIN_WINDOW_SECONDS:
            _login_attempts[ip] = {
                'count': 1,
                'first_attempt': now,
                'blocked_until': None
            }
            return True, _LOGIN_MAX_ATTEMPTS - 1, ''

        # 在窗口内，检查是否已达上限
        if record['count'] >= _LOGIN_MAX_ATTEMPTS:
            _login_attempts[ip]['blocked_until'] = now + timedelta(seconds=_LOGIN_BLOCK_SECONDS)
            return False, 0, f'登录尝试次数过多，请{_LOGIN_BLOCK_SECONDS // 60}分钟后再试'

        return True, _LOGIN_MAX_ATTEMPTS - record['count'], ''
    else:
        _login_attempts[ip] = {
            'count': 1,
            'first_attempt': now,
            'blocked_until': None
        }
        return True, _LOGIN_MAX_ATTEMPTS - 1, ''


def record_login_failure(ip):
    """记录登录失败，增加计数"""
    now = datetime.now()
    record = _login_attempts.get(ip)
    if record:
        record['count'] += 1
    else:
        _login_attempts[ip] = {
            'count': 1,
            'first_attempt': now,
            'blocked_until': None
        }


def clear_login_rate_limit(ip):
    """登录成功后清除限流记录"""
    _login_attempts.pop(ip, None)