"""
auth.py - 用户认证模块
负责处理用户注册、登录、登出、权限检查和语言偏好设置

这个文件是系统的"入口"，用户第一次使用系统时必须经过这里。
主要功能：
1. 用户注册：创建新账户和组织
2. 用户登录：验证身份并建立会话
3. 用户登出：清除会话信息
4. 语言设置：支持国际化多语言切换
5. 认证状态检查：验证用户是否已登录
6. 用户信息获取：返回当前登录用户的详细信息（包括权限）

安全要点：
- 密码不存储明文，使用 Werkzeug 的密码哈希函数存储
- 会话使用 Flask 的 session 管理，存储在加密 Cookie 中
- 使用事务保证数据一致性，注册失败自动回滚
- 邮箱唯一性约束，防止重复注册
"""
import sqlite3

from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db,          # 数据库连接上下文管理器
    login_required,  # 认证检查装饰器
    _t,              # 国际化翻译函数
    generate_password_hash,  # 密码哈希生成（明文转不可逆哈希）
    check_password_hash,      # 密码哈希验证（输入明文比对哈希）
    log_action,       # 记录操作审计日志
    logger,           # 日志记录器
    _normalize_locale, # 标准化语言代码
    _i18n_get_locale,  # 获取当前语言
    ROLES,             # 角色定义字典（包含权限列表）
    check_login_rate_limit,   # 登录速率限制检查
    record_login_failure,     # 记录登录失败
    clear_login_rate_limit    # 登录成功清除限流
)

# 创建认证蓝图，所有认证相关路由都在这个蓝图下
# 蓝图是 Flask 中组织路由的方式，可以把不同功能的路由分开
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/i18n/language', methods=['GET', 'POST'])
def api_i18n_language():
    """读取或更新当前会话语言偏好
    
    支持两种请求方式：
    - GET 请求：读取当前语言设置
    - POST 请求：更新语言设置并保存到数据库
    
    语言代码优先级（从高到低）：
    1. POST 请求中的 locale 参数
    2. URL 参数中的 lang
    3. 会话中已保存的 preferred_lang
    4. 浏览器默认语言
    """
    if request.method == 'GET':
        # 读取当前语言：依次检查会话、URL参数、浏览器语言
        locale = _normalize_locale(session.get('preferred_lang') or request.args.get('lang') or _i18n_get_locale())
        return jsonify({'locale': locale, 'supported': ['zh', 'en', 'ja', 'ko']})

    # POST 请求：更新语言设置
    data = request.get_json(silent=True) or {}
    locale = _normalize_locale(data.get('locale') or request.args.get('lang') or session.get('preferred_lang'))
    session['preferred_lang'] = locale  # 先更新会话中的语言

    # 如果用户已登录，同时更新数据库中的语言偏好
    if 'user_id' in session:
        with get_db() as conn:
            conn.execute('UPDATE users SET preferred_lang = ? WHERE id = ?', (locale, session['user_id']))
            conn.commit()

    return jsonify({'success': True, 'locale': locale})


@auth_bp.route('/api/auth/register', methods=['POST'])
def auth_register():
    """用户注册
    
    注册流程：
    1. 验证必填字段（用户名、邮箱、密码）
    2. 检查密码长度是否符合要求（至少8个字符）
    3. 创建组织记录（每个用户都属于一个组织，即使是个人工作区）
    4. 创建用户记录，密码存储为哈希值（不存储明文）
    5. 建立会话，用户注册后直接登录
    6. 如果邮箱已存在，回滚事务并返回错误
    
    数据一致性：使用数据库事务，任何一步失败都会回滚，不会产生脏数据
    """
    try:
        # 解析请求体中的JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': _t('error.emptyBody', '请求体不能为空')}), 400

        # 提取并清理输入数据，去除首尾空格
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        org_name = data.get('org_name', '个人工作区').strip()
        # 获取用户选择的语言偏好
        preferred_lang = _normalize_locale(data.get('preferred_lang') or request.args.get('lang') or session.get('preferred_lang'))
        
        # 必填字段验证
        if not all([username, email, password]):
            return jsonify({'error': _t('error.emptyField', '必填字段不能为空')}), 400
        
        # 密码长度验证，太短不安全
        if len(password) < 8:
            return jsonify({'error': _t('error.passwordTooShort', '密码至少8个字符')}), 400
        
        # 开始数据库事务
        with get_db() as conn:
            c = conn.cursor()
            
            try:
                # 第一步：创建组织（每个用户必须属于一个组织）
                # 即使是个人用户，也创建一个名为"个人工作区"的组织
                c.execute('INSERT INTO organizations (name) VALUES (?)', (org_name,))
                org_id = c.lastrowid  # 获取刚插入的组织ID
                
                # 第二步：密码加密，生成不可逆的哈希值
                # 即使数据库泄露，攻击者也无法获取明文密码
                hashed_pwd = generate_password_hash(password)
                
                # 第三步：创建用户记录，角色默认为admin（组织管理员）
                c.execute('''INSERT INTO users (username, email, password_hash, org_id, role_type, preferred_lang) 
                            VALUES (?, ?, ?, ?, ?, ?)''',
                         (username, email, hashed_pwd, org_id, 'org_admin', preferred_lang))
                user_id = c.lastrowid  # 获取刚插入的用户ID
                
                # 提交事务，所有更改写入数据库
                conn.commit()
                
                # 注册成功后，直接建立会话（用户不用再登录一次）
                session.clear()  # 清除可能存在的旧会话
                session['user_id'] = user_id        # 用户ID
                session['org_id'] = org_id          # 组织ID
                session['username'] = username      # 用户名
                session['role'] = 'org_admin'            # 角色类型（注册用户默认为组织管理员）
                session['preferred_lang'] = preferred_lang  # 语言偏好
                
                # 记录注册成功日志，方便后续排查问题
                logger.info(f"新用户注册: {email}, org_id={org_id}")
                
                return jsonify({
                    'success': True,
                    'message': _t('auth.registerSuccess', '注册成功'),
                    'user_id': user_id,
                    'org_id': org_id,
                    'username': username
                })
            except sqlite3.IntegrityError:
                # 捕获唯一性约束冲突：邮箱重复了
                conn.rollback()  # 回滚事务，不创建任何数据
                return jsonify({'error': _t('error.emailUsed', '邮箱已被使用')}), 400
    
    except Exception as e:
        # 捕获其他所有异常，记录日志，返回友好错误信息
        logger.error(f"注册失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.serverError', '注册失败，请稍后重试')}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    """用户登录
    
    登录流程：
    1. 验证必填字段（邮箱或用户名 + 密码）
    2. 在数据库中查找用户（支持邮箱或用户名登录）
    3. 验证密码哈希值是否匹配
    4. 检查账户是否被停用
    5. 建立会话并返回成功信息
    
    安全措施：
    - 使用哈希比对验证密码，不存储明文
    - 登录失败记录日志，方便发现异常登录尝试
    - 账户被停用后无法登录，即使密码正确
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': _t('error.emptyBody', '请求体不能为空')}), 400

        # 提取登录信息，支持邮箱或用户名两种方式
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        preferred_lang = _normalize_locale(data.get('preferred_lang') or request.args.get('lang') or session.get('preferred_lang'))
        
        # 必须提供邮箱或用户名，以及密码
        if not (email or username) or not password:
            return jsonify({'error': _t('error.emptyField', '必填字段不能为空')}), 400

        # 登录速率限制：防止暴力破解
        client_ip = request.remote_addr or 'unknown'
        allowed, remaining, limit_msg = check_login_rate_limit(client_ip)
        if not allowed:
            logger.warning(f"登录限流触发: ip={client_ip}")
            return jsonify({'error': limit_msg}), 429

        # 查询用户：使用 OR 条件，支持邮箱或用户名登录
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT id, username, org_id, role_type, password_hash, is_active, preferred_lang FROM users 
                         WHERE email = ? OR username = ?''', (email, username))
            user = c.fetchone()
        
        # 验证密码：将用户输入的密码与数据库中的哈希值比对
        # 如果用户不存在或密码不匹配，统一返回模糊错误，不明确告知是哪种错误
        # 这样可以防止攻击者通过错误信息猜测有效用户名
        if not user or not check_password_hash(user['password_hash'], password):
            logger.warning(f"登录失败: email={email}, username={username}")
            record_login_failure(client_ip)
            return jsonify({'error': _t('error.wrongCredentials', '邮箱或用户名或密码错误')}), 401
        
        # 检查账户是否被停用（is_active = 0 表示被管理员停用）
        if not user['is_active']:
            logger.warning(f"已停用账户尝试登录: {user['username']}")
            return jsonify({'error': _t('error.accountDisabled', '账户已被停用，请联系管理员')}), 403
        
        # 登录成功，建立会话
        session.clear()  # 清除旧会话，防止会话固定攻击
        session['user_id'] = user['id']              # 用户ID
        session['org_id'] = user['org_id']            # 组织ID
        session['username'] = user['username']        # 用户名
        session['role'] = user['role_type']           # 角色类型（用于权限控制）
        session['preferred_lang'] = _normalize_locale(user['preferred_lang'] or preferred_lang)  # 语言偏好
        
        logger.info(f"用户登录成功: {user['username']}")
        clear_login_rate_limit(client_ip)
        
        return jsonify({
            'success': True,
            'user_id': user['id'],
            'org_id': user['org_id'],
            'username': user['username']
        })
    
    except Exception as e:
        logger.error(f"登录失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.serverError', '登录失败，请稍后重试')}), 500


@auth_bp.route('/api/auth/check', methods=['GET'])
def auth_check():
    """检查认证状态
    
    前端页面加载时调用此接口，检测用户是否已经登录。
    如果已登录，返回用户信息；如果未登录，返回 authenticated=false。
    前端根据此结果决定显示登录页面还是主页面。
    """
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user_id': session.get('user_id'),
            'org_id': session.get('org_id'),
            'username': session.get('username'),
            'preferred_lang': _normalize_locale(session.get('preferred_lang', 'zh'))
        })
    return jsonify({'authenticated': False}), 200


# 以下是一些兼容旧版API的别名路由
# 保留这些是为了兼容旧版前端或第三方调用
@auth_bp.route('/api/check_auth', methods=['GET'])
def api_check_auth():
    return auth_check()


@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    return auth_login()


@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    return auth_register()


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    return auth_logout()


@auth_bp.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """用户登出
    
    登出操作非常简单：清除所有会话数据。
    清除后，所有需要 login_required 装饰器的接口都将返回 401 未登录。
    """
    session.clear()
    return jsonify({'success': True})


@auth_bp.route('/api/user_profile', methods=['GET'])
@login_required
def get_user_profile():
    """获取当前用户信息（增强版，含权限）
    
    返回当前登录用户的详细信息，包括：
    - 基本信息：用户名、邮箱、创建时间
    - 角色信息：角色类型、角色标签、权限列表
    - 组织信息：所属组织名称
    - 语言偏好
    
    前端使用此接口来显示用户信息、控制菜单权限
    """
    try:
        user_id = session.get('user_id')
        org_id = session.get('org_id')
        role_type = session.get('role', 'viewer')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, username, email, role_type, preferred_lang, created_at FROM users WHERE id=?', (user_id,))
            user = c.fetchone()
            if not user:
                return jsonify({'error': _t('error.userNotFound', '用户不存在')}), 404
            c.execute('SELECT name FROM organizations WHERE id=?', (org_id,))
            org = c.fetchone()
        
        # 获取角色信息，包含权限列表
        role_info = ROLES.get(role_type, {'label': role_type, 'permissions': []})
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'], 'username': user['username'], 'email': user['email'],
                'role_type': role_type,
                'role_label': role_info['label'],       # 角色中文标签
                'permissions': role_info['permissions'], # 用户拥有的权限列表
                'preferred_lang': user['preferred_lang'] or 'zh',
                'organization': org['name'] if org else None,
                'created_at': user['created_at']
            }
        })
    except Exception as e:
        logger.error(f"获取用户信息失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@auth_bp.route('/api/user/language', methods=['PUT'])
@login_required
def update_user_language():
    """更新用户语言偏好
    
    用户在设置页面切换语言时调用此接口。
    支持的语言：zh（中文）、en（英文）、ja（日文）、ko（韩文）
    """
    try:
        data = request.get_json(silent=True) or {}
        lang = data.get('lang', 'zh')
        if lang not in ('zh', 'en', 'ja', 'ko'):
            return jsonify({'error': _t('error.invalidLanguage', '无效的语言')}), 400
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE users SET preferred_lang=? WHERE id=?', (lang, session['user_id']))
            conn.commit()
        session['preferred_lang'] = lang
        return jsonify({'success': True, 'preferred_lang': lang})
    except Exception as e:
        logger.error(f"更新语言偏好失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500