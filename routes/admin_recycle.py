"""
admin_recycle.py - 回收站模块
提供回收站列表、恢复、彻底删除和自动清理功能。

从 admin.py 拆分出来，独立管理回收站相关路由。
"""
from flask import request, jsonify, session
from routes.shared import (
    get_db, require_permission,
    _t, logger, log_action, parse_pagination,
    RECYCLE_RESOURCES,
)


def auto_cleanup_recycle(org_id=None):
    total_cleaned = 0
    try:
        with get_db() as conn:
            c = conn.cursor()
            for rt_key, info in RECYCLE_RESOURCES.items():
                table = info['table']
                if org_id:
                    c.execute(f'''DELETE FROM {table}
                                 WHERE org_id=? AND is_deleted=1
                                 AND datetime(deleted_at, '+30 days') < datetime('now')''',
                             (org_id,))
                else:
                    c.execute(f'''DELETE FROM {table}
                                 WHERE is_deleted=1
                                 AND datetime(deleted_at, '+30 days') < datetime('now')''')
                total_cleaned += c.rowcount
            conn.commit()
        if total_cleaned > 0:
            logger.info(f"回收站自动清理完成: {total_cleaned} 项")
    except Exception as e:
        logger.error(f"回收站自动清理异常: {e}")
    return total_cleaned


def register_recycle_routes(bp):

    @bp.route('/api/recycle', methods=['GET'])
    @require_permission('qrcode:view')
    def api_recycle_list():
        try:
            org_id = session.get('org_id')
            page, size, offset = parse_pagination()
            resource_type = (request.args.get('type') or '').strip()
            keyword = (request.args.get('keyword') or '').strip()

            items = []
            total = 0

            with get_db() as conn:
                c = conn.cursor()

                for rt_key, info in RECYCLE_RESOURCES.items():
                    if resource_type and resource_type != rt_key:
                        continue
                    table = info['table']
                    title_field = info['title_field']

                    if keyword:
                        if info['has_name']:
                            where_kw = f' AND {title_field} LIKE ?'
                        else:
                            where_kw = ' AND title LIKE ?'
                        c.execute(f'''SELECT COUNT(*) FROM {table}
                                     WHERE org_id=? AND is_deleted=1{where_kw}''',
                                 (org_id, f'%{keyword}%'))
                    else:
                        c.execute(f'''SELECT COUNT(*) FROM {table}
                                     WHERE org_id=? AND is_deleted=1''', (org_id,))
                    total += c.fetchone()[0]

            union_parts = []
            union_params = []

            for rt_key, info in RECYCLE_RESOURCES.items():
                if resource_type and resource_type != rt_key:
                    continue
                table = info['table']
                title_field = info['title_field']

                if keyword:
                    if info['has_name']:
                        kw = f' AND {title_field} LIKE ?'
                    else:
                        kw = ' AND title LIKE ?'
                    union_parts.append(f'''SELECT id, {title_field} as name, '{rt_key}' as resource_type,
                                          deleted_at, deleted_by FROM {table}
                                          WHERE org_id=? AND is_deleted=1{kw}''')
                    union_params.extend([org_id, f'%{keyword}%'])
                else:
                    union_parts.append(f'''SELECT id, {title_field} as name, '{rt_key}' as resource_type,
                                          deleted_at, deleted_by FROM {table}
                                          WHERE org_id=? AND is_deleted=1''')
                    union_params.append(org_id)

            if union_parts:
                union_sql = ' UNION ALL '.join(union_parts) + ' ORDER BY deleted_at DESC LIMIT ? OFFSET ?'
                c.execute(union_sql, union_params + [size, offset])
                rows = c.fetchall()

                for r in rows:
                    deleted_by_name = None
                    if r['deleted_by']:
                        c.execute('SELECT username FROM users WHERE id=?', (r['deleted_by'],))
                        u = c.fetchone()
                        deleted_by_name = u['username'] if u else None

                    items.append({
                        'id': r['id'],
                        'name': r['name'],
                        'resource_type': r['resource_type'],
                        'resource_type_label': {'qrcode': '二维码', 'form': '表单', 'file': '文件',
                                               'workorder': '工单', 'inspection': '巡检'}.get(r['resource_type'], r['resource_type']),
                        'deleted_at': r['deleted_at'],
                        'deleted_by': r['deleted_by'],
                        'deleted_by_name': deleted_by_name
                    })

            return jsonify({
                'success': True,
                'total': total,
                'page': page,
                'size': size,
                'total_pages': max(1, (total + size - 1) // size),
                'items': items
            })
        except Exception as e:
            logger.error(f"回收站列表查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/recycle/restore', methods=['POST'])
    @require_permission('qrcode:edit')
    def api_recycle_restore():
        try:
            org_id = session.get('org_id')
            data = request.get_json() or {}
            items = data.get('items', [])
            if not items:
                return jsonify({'error': _t('error.restoreItemRequired', '请指定要恢复的项目')}), 400

            with get_db() as conn:
                c = conn.cursor()
                restored = 0
                for item in items:
                    info = RECYCLE_RESOURCES.get(item.get('type'))
                    if not info:
                        continue
                    c.execute(f'''UPDATE {info['table']}
                                 SET is_deleted=0, deleted_by=NULL, deleted_at=NULL
                                 WHERE id=? AND org_id=? AND is_deleted=1''',
                             (item['id'], org_id))
                    if c.rowcount > 0:
                        restored += 1
                        log_action(f'recycle_restore_{item.get("type")}',
                                  target_type=item.get('type'),
                                  target_id=item['id'])
                conn.commit()

            return jsonify({'success': True, 'restored': restored, 'message': f'成功恢复 {restored} 项'})
        except Exception as e:
            logger.error(f"回收站恢复失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.restoreFailed')}), 500

    @bp.route('/api/recycle/permanent-delete', methods=['POST'])
    @require_permission('qrcode:delete')
    def api_recycle_permanent_delete():
        try:
            org_id = session.get('org_id')
            data = request.get_json() or {}
            items = data.get('items', [])
            if not items:
                return jsonify({'error': _t('error.deleteItemRequired', '请指定要删除的项目')}), 400

            with get_db() as conn:
                c = conn.cursor()
                deleted = 0
                for item in items:
                    info = RECYCLE_RESOURCES.get(item.get('type'))
                    if not info:
                        continue
                    c.execute(f'''DELETE FROM {info['table']}
                                 WHERE id=? AND org_id=? AND is_deleted=1''',
                             (item['id'], org_id))
                    if c.rowcount > 0:
                        deleted += 1
                        log_action(f'recycle_delete_{item.get("type")}',
                                  target_type=item.get('type'),
                                  target_id=item['id'])
                conn.commit()

            return jsonify({'success': True, 'deleted': deleted, 'message': f'成功删除 {deleted} 项'})
        except Exception as e:
            logger.error(f"回收站彻底删除失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.deleteFailed')}), 500

    @bp.route('/api/recycle/cleanup', methods=['POST'])
    @require_permission('qrcode:delete')
    def api_recycle_cleanup():
        try:
            org_id = session.get('org_id')
            cleaned = auto_cleanup_recycle(org_id)
            return jsonify({
                'success': True,
                'cleaned': cleaned,
                'message': f'已清理 {cleaned} 项过期记录'
            })
        except Exception as e:
            logger.error(f"回收站自动清理失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.cleanupFailed', '清理失败')}), 500