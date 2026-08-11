"""智码云（SmartCode）企业级二维码管理平台 v2.0

这是一个基于 Flask 框架的 Web 应用，支持：
1. 二维码生成与管理（静态码、活码）
2. 表单创建与数据收集
3. 工单系统（创建、分配、处理）
4. 资产管理（绑定二维码、巡检计划）
5. 工作流自动化引擎
6. 组织架构与权限管理（RBAC）
7. 多语言国际化支持（中文、英文、日文、韩文）
8. OpenAPI 开放平台（API Key + JWT + OAuth2）
9. 订阅与计费系统
10. 文件管理（上传、下载、预览）
"""

# ============ 导入必要的库 ============
import os
import socket
import secrets

import flask

from flask import Flask, request, jsonify, session, render_template, redirect
from flask_cors import CORS
from routes.shared import _safe_t, _normalize_locale, Config, UPLOAD_FOLDER, MAX_FILE_SIZE, logger, login_required_page
from backend_i18n import get_locale as _i18n_get_locale

# ============ 基础路径配置 ============
# BASE_DIR 是项目根目录的绝对路径，用于定位模板文件和静态文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============ Flask 应用初始化 ============
# 创建 Flask 应用实例，指定模板文件夹和静态文件文件夹
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),  # HTML 模板目录
    static_folder=os.path.join(BASE_DIR, 'static')         # CSS/JS/图片等静态资源目录
)
# 启用跨域资源共享（CORS），允许前端从不同域名访问后端 API
CORS(app)

# ============ 解决中文 JSON 编码问题 ============
# Flask 默认会将 JSON 中的中文转义为 \uXXXX，这里确保中文直接显示
# 适配不同版本的 Flask（2.2+ 版本使用 DefaultJSONProvider）
if tuple(int(x) for x in flask.__version__.split('.')[:2]) >= (2, 2):
    from flask.json.provider import DefaultJSONProvider
    DefaultJSONProvider.ensure_ascii = False  # 新版 Flask 的配置方式
else:
    app.config['JSON_ENSURE_ASCII'] = False   # 旧版 Flask 的配置方式

# ============ 导入所有功能模块的蓝图（Blueprint） ============
# 蓝图是 Flask 中组织路由的方式，每个功能模块注册一个蓝图
# 这样做的好处：代码按功能分离，易于维护和扩展
from routes.auth import auth_bp               # 认证模块：注册、登录、登出
from routes.qr_management import qr_management_bp  # 二维码管理模块：活码/静态码管理、扫码跳转（生成已迁至 qrkit 内核）
from routes.form import form_bp               # 表单模块：创建、提交、数据收集
from routes.workorder import workorder_bp     # 工单模块：创建、分配、处理工单
from routes.asset import asset_bp             # 资产模块：资产管理、绑定二维码
from routes.inspection import inspection_bp   # 巡检模块：巡检计划、记录管理
from routes.department import department_bp   # 组织架构：部门树、人员管理
from routes.notification import notification_bp  # 通知模块：站内通知、Webhook
from routes.workflow import workflow_bp       # 工作流：自动化流程引擎
from routes.subscription import subscription_bp  # 订阅模块：套餐管理、付费
from routes.workspace import workspace_bp     # 工作台：仪表盘、统一搜索
from routes.open_api import open_api_bp       # 开放平台：API Key、JWT、OAuth2
from routes.file_mgr import file_bp           # 文件管理：上传、下载、文件库
from routes.admin import admin_bp             # 管理后台：用户管理、审计日志
from routes.qrkit.api import qrkit_bp          # 二维码内核：新一代生成引擎(P0)

# ============ 注册所有蓝图到 Flask 应用 ============
# 将每个功能模块的蓝图注册到应用中，使其路由生效
for bp in [auth_bp, qr_management_bp, form_bp, workorder_bp, asset_bp, inspection_bp,
           department_bp, notification_bp, workflow_bp, subscription_bp,
           workspace_bp, open_api_bp, file_bp, admin_bp, qrkit_bp]:
    app.register_blueprint(bp)

# ============ 上下文处理器：注入国际化信息到所有模板 ============
@app.context_processor
def inject_i18n_context():
    """在所有模板中自动注入当前语言设置
    这样前端页面就能知道用户当前使用的是哪种语言，从而正确显示对应文本
    """
    locale = _normalize_locale(session.get('preferred_lang') or request.args.get('lang') or _i18n_get_locale())
    return {'initial_locale': locale}

# ============ CSRF 防护 ============
@app.context_processor
def inject_csrf_token():
    """生成（每个会话仅一次）并向所有模板暴露 CSRF token。"""
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_hex(32)
        session['_csrf_token'] = token
    return {'csrf_token': token}

@app.before_request
def csrf_protect():
    """对状态变更的请求校验 CSRF token。

    豁免：
    - 安全方法（GET / HEAD / OPTIONS / TRACE）
    - 使用 Bearer JWT 或 X-API-Key 的程序化 API 客户端（开放平台）
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return
    # 程序化客户端通过 API Key / JWT 鉴权，不走会话 CSRF
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer ') or request.headers.get('X-API-Key'):
        return
    # 公开二维码生成内核：不落库、无需登录，且可能在预览沙箱中运行，豁免 CSRF
    if request.path.startswith('/api/qr/'):
        return
    # token 优先取请求头（fetch），其次取表单字段（传统表单 POST）
    token = request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token')
    ct = request.content_type or ''
    if not token and ('form-urlencoded' in ct or 'multipart/form-data' in ct):
        token = request.form.get('csrf_token')
    if not token or token != session.get('_csrf_token'):
        return jsonify({'error': _safe_t('error.csrf', '请求校验失败，请刷新页面后重试')}), 403

# 将配置应用到 Flask 应用
app.secret_key = Config.SECRET_KEY

# 确保上传目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ============ Flask 安全配置 ============
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
# 会话 Cookie 安全设置
app.config['SESSION_COOKIE_HTTPONLY'] = True   # 防止 JavaScript 读取 Cookie（防 XSS 攻击）
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # 防止跨站请求伪造（CSRF）
# 判断是否为本地环境，决定是否使用 HTTPS 安全 Cookie
hostname = socket.gethostname()
is_local = hostname in ['localhost', '127.0.0.1'] or socket.gethostbyname(hostname).startswith(('127.', '192.168.', '10.', '172.'))
app.config['SESSION_COOKIE_SECURE'] = not is_local and not Config.DEBUG  # 非本地环境强制使用 HTTPS

# ============ 安全响应头 ============
@app.after_request
def add_security_headers(response):
    """在每个 HTTP 响应中添加安全相关的头部信息
    这些头部可以防止常见的 Web 攻击：
    - Cache-Control: 防止敏感信息被浏览器缓存
    - X-Content-Type-Options: 防止浏览器 MIME 类型嗅探攻击
    - X-Frame-Options: 防止页面被嵌入到 iframe 中（防点击劫持）
    - X-XSS-Protection: 启用浏览器的 XSS 过滤器
    """
    for k, v in [('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
                 ('Pragma', 'no-cache'), ('Expires', '0'),
                 ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
                 ('X-XSS-Protection', '1; mode=block')]:
        response.headers[k] = v
    return response

# ============ 全局错误处理 ============
@app.errorhandler(500)
def handle_500_error(e):
    """处理服务器内部错误（500）
    记录详细的错误信息到日志，但只向前端返回友好的错误提示
    """
    logger.error(f"500 Internal Server Error: {e}", exc_info=True)
    return jsonify({'error': _safe_t('error.serverError')}), 500

@app.errorhandler(404)
def handle_404_error(e):
    """处理资源未找到错误（404）"""
    return jsonify({'error': _safe_t('error.fileNotFound', '资源不存在')}), 404

@app.errorhandler(403)
def handle_403_error(e):
    """处理权限不足错误（403）"""
    return jsonify({'error': _safe_t('error.noPermission', '权限不足')}), 403

@app.errorhandler(400)
def handle_400_error(e):
    """处理请求无效错误（400）"""
    return jsonify({'error': _safe_t('error.emptyBody', '请求无效')}), 400

# ============ 初始化数据库 ============
# 在应用启动时自动创建所有需要的数据库表（如果不存在的话）
from db_schema import init_db
init_db()

# ============ 页面路由（前端页面入口） ============

@app.route('/')
def index():
    """首页路由
    如果用户已登录，显示管理后台首页（index.html）
    如果用户未登录，显示营销落地页（home.html）
    """
    if 'user_id' in session:
        return render_template('index.html')
    return render_template('home.html')

@app.route('/app')
@login_required_page
def app_page():
    """应用主页面（需要登录）
    未登录用户会被重定向到首页
    """
    return render_template('index.html')

@app.route('/generator')
def generator_page():
    """新版二维码生成器（公开，基于 qrkit 内核，无需登录）"""
    from routes.qrkit.types import registry
    # 服务端直出类型 schema，避免预览沙箱中 fetch 被拦截导致无法选择类型
    return render_template('qr_generator.html', types=registry.describe())


@app.route('/dashboard')
@login_required_page
def dashboard():
    """仪表盘页面（需要登录）"""
    return render_template('dashboard.html')

@app.route('/scene')
def scene_page():
    """应用场景展示页面（无需登录，用于营销）"""
    return render_template('scene.html')

@app.route('/templates-center')
def templates_center_page():
    """模板中心页面（无需登录）"""
    return render_template('template_center.html')

@app.route('/collection/new')
@login_required_page
def collection_new_page():
    """创建新合集页面（需要登录）"""
    return render_template('collection_editor.html')

@app.route('/collection/<int:collection_id>/edit')
@login_required_page
def collection_edit_page(collection_id):
    """编辑合集页面（需要登录）"""
    return render_template('collection_editor.html', collection_id=collection_id)

@app.route('/my-space')
@login_required_page
def my_space_page():
    """个人空间页面（需要登录）"""
    return render_template('my_space.html')

# ============ 应用启动入口 ============
if __name__ == '__main__':
    logger.info(f"智码云启动中... (debug={Config.DEBUG})")
    # host='0.0.0.0' 表示监听所有网络接口，允许局域网内其他设备访问
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=5000)