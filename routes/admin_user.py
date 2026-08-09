"""
admin_user.py - 用户管理模块
提供组织内用户的列表、邀请、角色修改和启停管理。

从 admin.py 拆分出来，独立管理用户相关路由。
"""
from flask import request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, logger, check_quota, update_org_quota,
    generate_password_hash, log_action, ROLES,
)


def register_user_routes(bp):

    @bp.route('/api/users/list', methods=['GET'])
    @require_permission('user:manage')
    def list_users():
        try:
            org_id = session.get('org_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT id, username, email, role_type, is_active, created_at, last_login
                            FROM users WHERE org_id=? AND is_active=1 ORDER BY created_at DESC''', (org_id,))
                rows = c.fetchall()
            users = [{
                'id': r['id'], 'username': r['username'], 'email': r['email'],
                'role_type': r['role_type'], 'is_active': r['is_active'],
                'created_at': r['created_at'], 'last_login': r['last_login']
            } for r in rows]
            return jsonify({'success': True, 'users': users})
        except Exception as e:
            logger.error(f"用户列表查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/users', methods=['GET'])
    @login_required
    def api_users_brief():
        try:
            org_id = session.get('org_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id, username, email FROM users WHERE org_id=? AND is_active=1 ORDER BY username', (org_id,))
                rows = c.fetchall()
            users = [{'id': r['id'], 'username': r['username'], 'email': r['email']} for r in rows]
            return jsonify({'success': True, 'users': users})
        except Exception as e:
            logger.error(f"用户列表查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/users/invite', methods=['POST'])
    @require_permission('user:manage')
    def invite_user():
        try:
            data = request.get_json(silent=True) or {}
            org_id = session.get('org_id')
            username = (data.get('username') or '').strip()

            passed, limit, used, msg = check_quota(org_id, 'max_users')
            if not passed:
                return jsonify({'error': msg, 'quota': {'limit': limit, 'used': used}, 'upgrade_url': '/#subscription'}), 403
            email = (data.get('email') or '').strip()
            password = data.get('password') or ''
            role_type = data.get('role_type', 'editor')

            if role_type not in ROLES:
                return jsonify({'error': _t('error.invalidRoleType', '无效的角色类型')}), 400
            if not username or not email or not password:
                return jsonify({'error': _t('error.usernameEmailPasswordRequired', '用户名、邮箱、密码不能为空')}), 400
            if len(password) < 8:
                return jsonify({'error': _t('error.passwordTooShort', '密码至少8个字符')}), 400

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id FROM users WHERE email=?', (email,))
                if c.fetchone():
                    return jsonify({'error': _t('error.emailAlreadyUsed')}), 400

                password_hash = generate_password_hash(password)
                c.execute('''INSERT INTO users (username, email, password_hash, org_id, role_type, invited_by)
                            VALUES (?,?,?,?,?,?)''',
                         (username, email, password_hash, org_id, role_type, session.get('user_id')))
                user_id = c.lastrowid
                conn.commit()

            update_org_quota(org_id, 'max_users', 1)
            log_action('invite_user', 'user', user_id)
            return jsonify({'success': True, 'user_id': user_id})
        except Exception as e:
            logger.error(f"邀请用户失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.inviteFailed', '邀请失败')}), 500

    @bp.route('/api/users/<int:user_id>/role', methods=['PUT'])
    @require_permission('user:manage')
    def change_user_role(user_id):
        try:
            data = request.get_json(silent=True) or {}
            role_type = data.get('role_type', 'editor')
            org_id = session.get('org_id')

            if role_type not in ROLES:
                return jsonify({'error': _t('error.invalidRoleType', '无效的角色类型')}), 400

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id, role_type, org_id FROM users WHERE id=?', (user_id,))
                user = c.fetchone()
                if not user or user['org_id'] != org_id:
                    return jsonify({'error': _t('error.userNotFound')}), 404

                if user['role_type'] == 'super_admin':
                    return jsonify({'error': _t('error.superAdmin')}), 403

                c.execute('UPDATE users SET role_type=? WHERE id=?', (role_type, user_id))
                conn.commit()

            log_action('change_role', 'user', user_id, {'new_role': role_type})
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"修改角色失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.modifyFailed', '修改失败')}), 500

    @bp.route('/api/users/<int:user_id>/toggle', methods=['POST'])
    @require_permission('user:manage')
    def toggle_user(user_id):
        try:
            org_id = session.get('org_id')
            current_user_id = session.get('user_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id, role_type, is_active, org_id FROM users WHERE id=?', (user_id,))
                user = c.fetchone()
                if not user or user['org_id'] != org_id:
                    return jsonify({'error': _t('error.userNotFound', '用户不存在')}), 404

                if user_id == current_user_id:
                    return jsonify({'error': _t('error.cannotDisableSelf', '不能禁用自己')}), 403
                if user['role_type'] == 'super_admin':
                    return jsonify({'error': _t('error.cannotDisableSuperAdmin', '不能禁用超级管理员')}), 403

                new_status = 0 if user['is_active'] else 1
                c.execute('UPDATE users SET is_active=? WHERE id=?', (new_status, user_id))
                conn.commit()

            log_action('toggle_user', 'user', user_id)
            return jsonify({'success': True, 'is_active': new_status})
        except Exception as e:
            logger.error(f"切换用户状态失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500