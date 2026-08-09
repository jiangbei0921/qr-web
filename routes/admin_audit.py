"""
admin_audit.py - 审计日志模块
提供审计日志的查询、详情查看和筛选选项功能。

从 admin.py 拆分出来，独立管理审计日志相关路由。
"""
import json

from flask import request, jsonify, session
from routes.shared import (
    get_db, require_permission,
    _t, logger, parse_pagination,
)


def register_audit_routes(bp):

    @bp.route('/api/audit', methods=['GET'])
    @require_permission('audit:view')
    def api_audit_logs():
        try:
            org_id = session.get('org_id')
            page, size, offset = parse_pagination()
            user_id = request.args.get('user_id', '').strip()
            action = request.args.get('action', '').strip()
            resource_type = request.args.get('resource_type', '').strip()
            resource_id = request.args.get('resource_id', '').strip()
            start_date = request.args.get('start_date', '').strip()
            end_date = request.args.get('end_date', '').strip()
            keyword = request.args.get('keyword', '').strip()

            with get_db() as conn:
                c = conn.cursor()
                where = 'WHERE a.org_id = ?'
                params = [org_id]

                if user_id:
                    where += ' AND a.user_id = ?'
                    params.append(int(user_id))
                if action:
                    where += ' AND a.action LIKE ?'
                    params.append(f'%{action}%')
                if resource_type:
                    where += ' AND (a.resource_type = ? OR a.target_type = ?)'
                    params.append(resource_type)
                    params.append(resource_type)
                if resource_id:
                    where += ' AND (a.resource_id = ? OR a.target_id = ?)'
                    params.append(int(resource_id))
                    params.append(int(resource_id))
                if start_date:
                    where += ' AND datetime(a.created_at) >= datetime(?)'
                    params.append(start_date)
                if end_date:
                    where += ' AND datetime(a.created_at) <= datetime(?)'
                    params.append(end_date + ' 23:59:59')
                if keyword:
                    where += ' AND (a.detail LIKE ? OR a.action LIKE ?)'
                    params.append(f'%{keyword}%')
                    params.append(f'%{keyword}%')

                c.execute(f'SELECT COUNT(*) FROM audit_logs a {where}', params)
                total = c.fetchone()[0]

                c.execute(f'''SELECT a.*, u.username
                            FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id
                            {where} ORDER BY a.created_at DESC LIMIT ? OFFSET ?''',
                         params + [size, offset])
                rows = c.fetchall()

            logs = []
            for r in rows:
                detail = None
                if r['detail']:
                    try:
                        detail = json.loads(r['detail'])
                    except (json.JSONDecodeError, TypeError):
                        detail = r['detail']
                before_data = None
                if r['before_data']:
                    try:
                        before_data = json.loads(r['before_data'])
                    except (json.JSONDecodeError, TypeError):
                        before_data = r['before_data']
                after_data = None
                if r['after_data']:
                    try:
                        after_data = json.loads(r['after_data'])
                    except (json.JSONDecodeError, TypeError):
                        after_data = r['after_data']

                logs.append({
                    'id': r['id'],
                    'user_id': r['user_id'],
                    'username': r['username'] or '系统',
                    'action': r['action'],
                    'resource_type': r['resource_type'] or r['target_type'] or '',
                    'resource_id': r['resource_id'] or r['target_id'],
                    'detail': detail,
                    'before_data': before_data,
                    'after_data': after_data,
                    'ip': r['ip'],
                    'user_agent': r['user_agent'],
                    'created_at': r['created_at']
                })

            return jsonify({
                'success': True,
                'total': total,
                'page': page,
                'size': size,
                'total_pages': max(1, (total + size - 1) // size),
                'logs': logs
            })
        except Exception as e:
            logger.error(f"审计日志查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/audit/<int:log_id>', methods=['GET'])
    @require_permission('audit:view')
    def api_audit_detail(log_id: int):
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT a.*, u.username
                            FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id
                            WHERE a.id = ? AND a.org_id = ?''', (log_id, org_id))
                r = c.fetchone()

                if not r:
                    return jsonify({'error': _t('error.logNotFound')}), 404

                detail = None
                if r['detail']:
                    try:
                        detail = json.loads(r['detail'])
                    except (json.JSONDecodeError, TypeError):
                        detail = r['detail']
                before_data = None
                if r['before_data']:
                    try:
                        before_data = json.loads(r['before_data'])
                    except (json.JSONDecodeError, TypeError):
                        before_data = r['before_data']
                after_data = None
                if r['after_data']:
                    try:
                        after_data = json.loads(r['after_data'])
                    except (json.JSONDecodeError, TypeError):
                        after_data = r['after_data']

            return jsonify({
                'success': True,
                'log': {
                    'id': r['id'],
                    'user_id': r['user_id'],
                    'username': r['username'] or '系统',
                    'action': r['action'],
                    'resource_type': r['resource_type'] or r['target_type'] or '',
                    'resource_id': r['resource_id'] or r['target_id'],
                    'detail': detail,
                    'before_data': before_data,
                    'after_data': after_data,
                    'ip': r['ip'],
                    'user_agent': r['user_agent'],
                    'created_at': r['created_at']
                }
            })
        except Exception as e:
            logger.error(f"审计日志详情查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/audit/filters', methods=['GET'])
    @require_permission('audit:view')
    def api_audit_filters():
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT DISTINCT COALESCE(a.resource_type, a.target_type) as rt
                            FROM audit_logs a WHERE a.org_id = ? AND COALESCE(a.resource_type, a.target_type) IS NOT NULL
                            ORDER BY rt''', (org_id,))
                resource_types = [r['rt'] for r in c.fetchall()]

                c.execute('''SELECT DISTINCT a.user_id, u.username
                            FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id
                            WHERE a.org_id = ? AND a.user_id IS NOT NULL
                            ORDER BY u.username''', (org_id,))
                users = [{'user_id': r['user_id'], 'username': r['username'] or '未知'} for r in c.fetchall()]

                c.execute('''SELECT DISTINCT a.action FROM audit_logs a
                            WHERE a.org_id = ? ORDER BY a.action''', (org_id,))
                actions = [r['action'] for r in c.fetchall()]

            return jsonify({
                'success': True,
                'resource_types': resource_types,
                'users': users,
                'actions': actions
            })
        except Exception as e:
            logger.error(f"审计筛选选项查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500