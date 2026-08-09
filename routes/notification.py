"""
notification.py - 通知中心模块
负责系统内通知的发送、接收和管理。

通知系统是连接系统事件和用户的桥梁，当系统中发生重要事件时，
会自动创建通知发送给相关用户。

主要功能：
1. 通知列表：分页查看、支持搜索和筛选
2. 未读计数：实时显示各类通知的未读数量
3. 已读标记：单条标记或全部标记已读
4. 通知归档：归档不重要的通知
5. 通知删除：软删除到回收站
6. 通知设置：配置各类通知的接收渠道
7. 通知统计：按类别统计通知数量

通知类别：
- system：系统通知（升级、维护等）
- qrcode：二维码相关通知（创建、修改等）
- workorder：工单通知（分配、解决等）
- inspection：巡检通知（提醒、逾期等）
- form：表单通知（提交、审批等）
- subscription：订阅通知（续费、过期等）
"""
import json
from datetime import datetime

from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, parse_pagination,
    NOTIFICATION_CATEGORIES,
    NOTIFICATION_LEVELS,
    DEFAULT_NOTIFICATION_SETTINGS
)

notification_bp = Blueprint('notification', __name__)


@notification_bp.route('/api/notifications', methods=['GET'])
@login_required
def api_notifications_list():
    """通知列表（分页+搜索+筛选）"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        page, size, offset = parse_pagination(max_size=50)
        category = (request.args.get('category') or '').strip()
        level = (request.args.get('level') or '').strip()
        status = (request.args.get('status') or '').strip()
        search = (request.args.get('q') or '').strip()

        with get_db() as conn:
            c = conn.cursor()
            where = ['n.org_id=?', 'n.is_deleted=0']
            params = [org_id]

            if user_id:
                where.append('(n.user_id=? OR n.user_id IS NULL)')
                params.append(user_id)

            if category:
                where.append('n.category=?')
                params.append(category)
            if level:
                where.append('n.level=?')
                params.append(level)
            if status == 'unread':
                where.append('n.is_read=0')
            elif status == 'read':
                where.append('n.is_read=1')
            elif status == 'archived':
                where.append('n.is_archived=1')
            else:
                where.append('n.is_archived=0')
            if search:
                where.append('(n.title LIKE ? OR n.content LIKE ?)')
                params.extend([f'%{search}%', f'%{search}%'])

            where_clause = ' AND '.join(where)
            c.execute(f'SELECT COUNT(*) FROM notifications n WHERE {where_clause}', params)
            total = c.fetchone()[0]

            c.execute(f'''SELECT n.* FROM notifications n
                        WHERE {where_clause}
                        ORDER BY n.created_at DESC LIMIT ? OFFSET ?''',
                     params + [size, offset])
            rows = c.fetchall()

        notifications = [{
            'id': r['id'], 'category': r['category'],
            'category_label': NOTIFICATION_CATEGORIES.get(r['category'], {}).get('label', r['category']),
            'category_icon': NOTIFICATION_CATEGORIES.get(r['category'], {}).get('icon', '🔔'),
            'category_color': NOTIFICATION_CATEGORIES.get(r['category'], {}).get('color', '#6366F1'),
            'title': r['title'], 'content': r['content'],
            'level': r['level'], 'level_label': NOTIFICATION_LEVELS.get(r['level'], {}).get('label', '信息'),
            'level_color': NOTIFICATION_LEVELS.get(r['level'], {}).get('color', '#1677FF'),
            'link': r['link'], 'is_read': bool(r['is_read']),
            'is_archived': bool(r['is_archived']),
            'source_type': r['source_type'], 'source_id': r['source_id'],
            'created_at': r['created_at'], 'read_at': r['read_at']
        } for r in rows]

        return jsonify({'success': True, 'total': total, 'page': page, 'size': size,
                       'total_pages': max(1, (total + size - 1) // size), 'notifications': notifications})
    except Exception as e:
        logger.error(f"通知列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@notification_bp.route('/api/notifications/unread-count', methods=['GET'])
@login_required
def api_notifications_unread_count():
    """未读通知计数"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        with get_db() as conn:
            c = conn.cursor()
            counts = {}

            c.execute('''SELECT COUNT(*) FROM notifications
                        WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                        AND is_read=0 AND is_deleted=0 AND is_archived=0''',
                     (org_id, user_id))
            counts['total'] = c.fetchone()[0]

            for cat in NOTIFICATION_CATEGORIES:
                c.execute('''SELECT COUNT(*) FROM notifications
                            WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                            AND category=? AND is_read=0 AND is_deleted=0 AND is_archived=0''',
                         (org_id, user_id, cat))
                counts[cat] = c.fetchone()[0]

        return jsonify({'success': True, 'unread': counts})
    except Exception as e:
        logger.error(f"未读计数查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@notification_bp.route('/api/notifications/<int:notif_id>/read', methods=['PUT'])
@login_required
def api_notification_read(notif_id):
    """标记单条已读"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''UPDATE notifications SET is_read=1, read_at=CURRENT_TIMESTAMP
                        WHERE id=? AND org_id=?''', (notif_id, org_id))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"标记已读失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500



@notification_bp.route('/api/notifications/read-all', methods=['PUT'])
@login_required
def api_notifications_read_all():
    """全部标记已读"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        category = (request.args.get('category') or '').strip()

        with get_db() as conn:
            c = conn.cursor()
            if category:
                c.execute('''UPDATE notifications SET is_read=1, read_at=CURRENT_TIMESTAMP
                            WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                            AND category=? AND is_read=0 AND is_deleted=0''',
                         (org_id, user_id, category))
            else:
                c.execute('''UPDATE notifications SET is_read=1, read_at=CURRENT_TIMESTAMP
                            WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                            AND is_read=0 AND is_deleted=0''',
                         (org_id, user_id))
            conn.commit()

        return jsonify({'success': True, 'message': '已全部标记为已读'})
    except Exception as e:
        logger.error(f"全部已读失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500



@notification_bp.route('/api/notifications/<int:notif_id>/archive', methods=['PUT'])
@login_required
def api_notification_archive(notif_id):
    """归档/取消归档通知"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        archived = bool(data.get('archive', True))

        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE notifications SET is_archived=? WHERE id=? AND org_id=?',
                     (int(archived), notif_id, org_id))
            conn.commit()

        return jsonify({'success': True, 'message': '已归档' if archived else '已取消归档'})
    except Exception as e:
        logger.error(f"归档失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500



@notification_bp.route('/api/notifications/<int:notif_id>', methods=['DELETE'])
@login_required
def api_notification_delete(notif_id):
    """删除通知（软删除）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE notifications SET is_deleted=1 WHERE id=? AND org_id=?',
                     (notif_id, org_id))
            conn.commit()
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        logger.error(f"删除通知失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500



@notification_bp.route('/api/notifications/statistics', methods=['GET'])
@login_required
def api_notifications_statistics():
    """通知统计"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        with get_db() as conn:
            c = conn.cursor()
            stats = {'total': 0, 'unread': 0, 'categories': {}}

            c.execute('''SELECT COUNT(*) FROM notifications
                        WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                        AND is_deleted=0 AND is_archived=0''',
                     (org_id, user_id))
            stats['total'] = c.fetchone()[0]

            c.execute('''SELECT COUNT(*) FROM notifications
                        WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                        AND is_read=0 AND is_deleted=0 AND is_archived=0''',
                     (org_id, user_id))
            stats['unread'] = c.fetchone()[0]

            for cat in NOTIFICATION_CATEGORIES:
                c.execute('''SELECT COUNT(*) as total,
                            SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) as unread
                            FROM notifications
                            WHERE org_id=? AND (user_id=? OR user_id IS NULL)
                            AND category=? AND is_deleted=0 AND is_archived=0''',
                         (org_id, user_id, cat))
                row = c.fetchone()
                stats['categories'][cat] = {
                    'label': NOTIFICATION_CATEGORIES[cat]['label'],
                    'icon': NOTIFICATION_CATEGORIES[cat]['icon'],
                    'color': NOTIFICATION_CATEGORIES[cat]['color'],
                    'total': row['total'] or 0,
                    'unread': row['unread'] or 0
                }

        return jsonify({'success': True, 'statistics': stats})
    except Exception as e:
        logger.error(f"通知统计失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@notification_bp.route('/api/notifications/settings', methods=['GET'])
@login_required
def api_notification_settings_get():
    """获取通知设置"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        settings = {}
        for cat in NOTIFICATION_CATEGORIES:
            settings[cat] = dict(DEFAULT_NOTIFICATION_SETTINGS[cat])
            settings[cat]['label'] = NOTIFICATION_CATEGORIES[cat]['label']
            settings[cat]['icon'] = NOTIFICATION_CATEGORIES[cat]['icon']

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM notification_settings WHERE org_id=? AND user_id=?',
                     (org_id, user_id))
            for row in c.fetchall():
                cat = row['category']
                if cat in settings:
                    settings[cat]['inapp'] = bool(row['channel_inapp'])
                    settings[cat]['email'] = bool(row['channel_email'])
                    settings[cat]['webhook'] = bool(row['channel_webhook'])
                    settings[cat]['sms'] = bool(row['channel_sms'])
                    settings[cat]['wechat'] = bool(row['channel_wechat'])

        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        logger.error(f"通知设置查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@notification_bp.route('/api/notifications/settings', methods=['PUT'])
@login_required
def api_notification_settings_update():
    """更新通知设置"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        settings = data.get('settings', {})

        with get_db() as conn:
            c = conn.cursor()
            for cat, channels in settings.items():
                if cat not in NOTIFICATION_CATEGORIES:
                    continue
                c.execute('''INSERT OR REPLACE INTO notification_settings
                    (org_id, user_id, category, channel_inapp, channel_email, channel_webhook, channel_sms, channel_wechat, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',
                    (org_id, user_id, cat,
                     int(channels.get('inapp', True)), int(channels.get('email', False)),
                     int(channels.get('webhook', False)), int(channels.get('sms', False)),
                     int(channels.get('wechat', False))))
            conn.commit()

        return jsonify({'success': True, 'message': '设置已保存'})
    except Exception as e:
        logger.error(f"通知设置更新失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.saveFailed', '保存失败')}), 500



@notification_bp.route('/api/webhooks', methods=['GET'])
@login_required
def api_webhooks_list():
    """Webhook 配置列表"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM webhook_configs WHERE org_id=? ORDER BY created_at DESC', (org_id,))
            rows = c.fetchall()

        webhooks = [{
            'id': r['id'], 'name': r['name'], 'url': r['url'],
            'secret': bool(r['secret']), 'events': json.loads(r['events'] or '[]'),
            'is_active': bool(r['is_active']), 'last_triggered_at': r['last_triggered_at'],
            'created_at': r['created_at']
        } for r in rows]

        return jsonify({'success': True, 'webhooks': webhooks})
    except Exception as e:
        logger.error(f"Webhook列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@notification_bp.route('/api/webhooks', methods=['POST'])
@login_required
def api_webhooks_create():
    """创建 Webhook 配置"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        name = (data.get('name') or '').strip()
        url = (data.get('url') or '').strip()
        secret = (data.get('secret') or '').strip()
        events = data.get('events', [])

        if not name or not url:
            return jsonify({'error': _t('error.nameAndUrl')}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO webhook_configs (org_id, name, url, secret, events)
                        VALUES (?,?,?,?,?)''',
                     (org_id, name, url, secret or None, json.dumps(events)))
            conn.commit()

        return jsonify({'success': True, 'message': 'Webhook创建成功'})
    except Exception as e:
        logger.error(f"Webhook创建失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@notification_bp.route('/api/webhooks/<int:webhook_id>', methods=['PUT'])
@login_required
def api_webhooks_update(webhook_id):
    """更新 Webhook 配置"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM webhook_configs WHERE id=? AND org_id=?', (webhook_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.webhookNotFound', 'Webhook不存在')}), 404

            updates = []
            params = []
            for field in ['name', 'url', 'secret']:
                val = data.get(field)
                if val is not None:
                    updates.append(f'{field}=?')
                    params.append(val.strip() if isinstance(val, str) else val)
            if 'events' in data:
                updates.append('events=?')
                params.append(json.dumps(data['events']))
            if 'is_active' in data:
                updates.append('is_active=?')
                params.append(int(data['is_active']))

            if updates:
                params.extend([webhook_id, org_id])
                c.execute(f'UPDATE webhook_configs SET {", ".join(updates)} WHERE id=? AND org_id=?', params)
                conn.commit()

        return jsonify({'success': True, 'message': 'Webhook已更新'})
    except Exception as e:
        logger.error(f"Webhook更新失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500



@notification_bp.route('/api/webhooks/<int:webhook_id>', methods=['DELETE'])
@login_required
def api_webhooks_delete(webhook_id):
    """删除 Webhook 配置"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM webhook_configs WHERE id=? AND org_id=?', (webhook_id, org_id))
            conn.commit()
        return jsonify({'success': True, 'message': 'Webhook已删除'})
    except Exception as e:
        logger.error(f"Webhook删除失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500



@notification_bp.route('/api/webhooks/<int:webhook_id>/test', methods=['POST'])
@login_required
def api_webhooks_test(webhook_id):
    """测试 Webhook"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM webhook_configs WHERE id=? AND org_id=?', (webhook_id, org_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': _t('error.webhookNotFound', 'Webhook不存在')}), 404

        test_payload = {
            'org_id': org_id, 'category': 'system', 'title': 'Webhook 测试',
            'content': '这是一条来自 SmartCode 的测试通知', 'level': 'info',
            'timestamp': datetime.now().isoformat(), 'test': True
        }
        _send_webhook_async(dict(row), test_payload)

        return jsonify({'success': True, 'message': '测试通知已发送'})
    except Exception as e:
        logger.error(f"Webhook测试失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.testFailed', '测试失败')}), 500


# ============ 回收站系统 ============

RECYCLE_RESOURCES = {
    'qrcode': {'table': 'qrcodes', 'title_field': 'title', 'has_name': False},
    'form': {'table': 'forms', 'title_field': 'form_name', 'has_name': True},
    'file': {'table': 'files', 'title_field': 'name', 'has_name': False},
    'workorder': {'table': 'workorders', 'title_field': 'title', 'has_name': False},
    'inspection': {'table': 'inspection_plans', 'title_field': "('巡检计划 #' || id)", 'has_name': True}
}


def soft_delete_resource(resource_type, resource_id, conn=None):
    """软删除资源（内部函数）"""
    info = RECYCLE_RESOURCES.get(resource_type)
    if not info:
        return False
    try:
        if conn:
            c = conn.cursor()
            c.execute(f'''UPDATE {info['table']} SET is_deleted=1,
                         deleted_by=?, deleted_at=datetime('now')
                         WHERE id=? AND org_id=?''',
                     (session.get('user_id'), resource_id, session.get('org_id')))
        else:
            with get_db() as db:
                c = db.cursor()
                c.execute(f'''UPDATE {info['table']} SET is_deleted=1,
                             deleted_by=?, deleted_at=datetime('now')
                             WHERE id=? AND org_id=?''',
                         (session.get('user_id'), resource_id, session.get('org_id')))
                db.commit()
        return True
    except Exception as e:
        logger.error(f"软删除失败 {resource_type}#{resource_id}: {e}")
        return False