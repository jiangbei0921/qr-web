"""
admin_version.py - 版本管理模块
提供版本的列表、详情、比较、回滚、备注和删除功能。

从 admin.py 拆分出来，独立管理版本相关路由。
"""
import json

from flask import request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, logger, log_action, save_version, parse_pagination,
)


def register_version_routes(bp):

    @bp.route('/api/versions', methods=['GET'])
    @login_required
    def api_versions_list():
        try:
            org_id = session.get('org_id')
            resource_type = (request.args.get('type') or '').strip()
            resource_id = request.args.get('id')
            page, size, offset = parse_pagination(max_size=50)

            if not resource_type or not resource_id:
                return jsonify({'error': _t('error.missingResourceType')}), 400

            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT COUNT(*) FROM resource_versions
                            WHERE org_id=? AND resource_type=? AND resource_id=?''',
                         (org_id, resource_type, resource_id))
                total = c.fetchone()[0]

                offset = (page - 1) * size
                c.execute('''SELECT rv.*, u.username as operator_name
                            FROM resource_versions rv LEFT JOIN users u ON rv.operator = u.id
                            WHERE rv.org_id=? AND rv.resource_type=? AND rv.resource_id=?
                            ORDER BY rv.version DESC LIMIT ? OFFSET ?''',
                         (org_id, resource_type, resource_id, size, offset))
                rows = c.fetchall()

            versions = [{
                'id': r['id'], 'resource_type': r['resource_type'],
                'resource_id': r['resource_id'], 'version': r['version'],
                'content_hash': r['content_hash'], 'remark': r['remark'],
                'operator': r['operator_name'] or '系统',
                'created_at': r['created_at']
            } for r in rows]

            return jsonify({'success': True, 'total': total, 'page': page, 'size': size,
                           'total_pages': max(1, (total + size - 1) // size), 'versions': versions})
        except Exception as e:
            logger.error(f"版本列表查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/versions/<int:version_id>', methods=['GET'])
    @login_required
    def api_version_detail(version_id):
        try:
            org_id = session.get('org_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT rv.*, u.username as operator_name
                            FROM resource_versions rv LEFT JOIN users u ON rv.operator = u.id
                            WHERE rv.id=? AND rv.org_id=?''', (version_id, org_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': _t('error.versionNotFound')}), 404

            return jsonify({
                'success': True,
                'version': {
                    'id': row['id'], 'resource_type': row['resource_type'],
                    'resource_id': row['resource_id'], 'version': row['version'],
                    'snapshot': json.loads(row['snapshot']),
                    'content_hash': row['content_hash'], 'remark': row['remark'],
                    'operator': row['operator_name'] or '系统',
                    'created_at': row['created_at']
                }
            })
        except Exception as e:
            logger.error(f"版本详情查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/versions/compare', methods=['GET'])
    @login_required
    def api_versions_compare():
        try:
            org_id = session.get('org_id')
            v1_id = int(request.args.get('v1', 0) or 0)
            v2_id = int(request.args.get('v2', 0) or 0)

            if not v1_id or not v2_id:
                return jsonify({'error': _t('error.twoVersionIds')}), 400

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM resource_versions WHERE id IN (?,?) AND org_id=?',
                         (v1_id, v2_id, org_id))
                rows = {r['id']: r for r in c.fetchall()}
                if len(rows) != 2:
                    return jsonify({'error': _t('error.versionNotFound', '版本不存在')}), 404

            snap1 = json.loads(rows[v1_id]['snapshot'])
            snap2 = json.loads(rows[v2_id]['snapshot'])

            all_keys = set(snap1) | set(snap2)
            diff = []
            for key in sorted(all_keys):
                v1 = snap1.get(key)
                v2 = snap2.get(key)
                if v1 != v2:
                    diff.append({
                        'field': key,
                        'old': v1,
                        'new': v2,
                        'changed': True
                    })
                else:
                    diff.append({
                        'field': key,
                        'value': v1,
                        'changed': False
                    })

            return jsonify({
                'success': True,
                'v1': {'id': rows[v1_id]['id'], 'version': rows[v1_id]['version'],
                       'created_at': rows[v1_id]['created_at']},
                'v2': {'id': rows[v2_id]['id'], 'version': rows[v2_id]['version'],
                       'created_at': rows[v2_id]['created_at']},
                'diff': diff,
                'changed_count': sum(1 for d in diff if d.get('changed'))
            })
        except Exception as e:
            logger.error(f"版本比较失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.compareFailed')}), 500

    @bp.route('/api/versions/rollback', methods=['POST'])
    @login_required
    @require_permission('version:rollback')
    def api_versions_rollback():
        try:
            data = request.get_json(silent=True) or {}
            version_id = data.get('version_id')
            remark = (data.get('remark') or '').strip()

            if not version_id:
                return jsonify({'error': _t('error.versionIdRequired', '缺少版本ID')}), 400

            org_id = session.get('org_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM resource_versions WHERE id=? AND org_id=?',
                         (version_id, org_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': _t('error.versionNotFound', '版本不存在')}), 404

                resource_type = row['resource_type']
                resource_id = row['resource_id']
                snapshot = json.loads(row['snapshot'])

                if resource_type == 'qrcode':
                    fields = ', '.join(f'{k}=?' for k in snapshot)
                    c.execute(f'UPDATE qrcodes SET {fields}, updated_at=CURRENT_TIMESTAMP WHERE id=? AND org_id=?',
                             list(snapshot.values()) + [resource_id, org_id])
                elif resource_type == 'form':
                    fields = ', '.join(f'{k}=?' for k in snapshot)
                    c.execute(f'UPDATE forms SET {fields}, updated_at=CURRENT_TIMESTAMP WHERE id=? AND org_id=?',
                             list(snapshot.values()) + [resource_id, org_id])
                else:
                    return jsonify({'error': f'不支持回滚的资源类型: {resource_type}'}), 400

                conn.commit()

            save_version(resource_type, resource_id, json.dumps(snapshot, ensure_ascii=False),
                        remark=f'回滚到 v{row["version"]}' + (f' - {remark}' if remark else ''))

            log_action('rollback_version', resource_type, resource_id,
                      {'from_version': row['version']})

            return jsonify({
                'success': True,
                'message': f'已回滚到版本 {row["version"]}',
                'restored_version': row['version']
            })
        except Exception as e:
            logger.error(f"版本回滚失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.rollbackFailed', '回滚失败')}), 500

    @bp.route('/api/versions/<int:version_id>/remark', methods=['PUT'])
    @login_required
    @require_permission('version:rollback')
    def api_version_remark(version_id):
        try:
            data = request.get_json(silent=True) or {}
            org_id = session.get('org_id')
            remark = (data.get('remark') or '').strip()

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id FROM resource_versions WHERE id=? AND org_id=?',
                         (version_id, org_id))
                if not c.fetchone():
                    return jsonify({'error': _t('error.versionNotFound')}), 404

                c.execute('UPDATE resource_versions SET remark=? WHERE id=? AND org_id=?',
                         (remark, version_id, org_id))
                conn.commit()

            return jsonify({'success': True, 'message': '备注已更新'})
        except Exception as e:
            logger.error(f"版本备注更新失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500

    @bp.route('/api/versions/<int:version_id>', methods=['DELETE'])
    @login_required
    @require_permission('version:delete')
    def api_version_delete(version_id):
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM resource_versions WHERE id=? AND org_id=?',
                         (version_id, org_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': _t('error.versionNotFound')}), 404

                c.execute('DELETE FROM resource_versions WHERE id=? AND org_id=?',
                         (version_id, org_id))
                conn.commit()

            log_action('delete_version', row['resource_type'], row['resource_id'],
                      {'deleted_version': row['version']})

            return jsonify({'success': True, 'message': '版本已删除'})
        except Exception as e:
            logger.error(f"版本删除失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500

    @bp.route('/api/versions/resource-summary', methods=['GET'])
    @login_required
    def api_version_resource_summary():
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT resource_type, COUNT(*) as version_count,
                            MAX(version) as latest_version, MAX(created_at) as last_updated
                            FROM resource_versions
                            WHERE org_id=?
                            GROUP BY resource_type
                            ORDER BY last_updated DESC''', (org_id,))
                rows = c.fetchall()

            summaries = [{
                'resource_type': r['resource_type'],
                'resource_type_label': {'qrcode': '二维码', 'form': '表单', 'template': '模板'}.get(r['resource_type'], r['resource_type']),
                'version_count': r['version_count'],
                'latest_version': r['latest_version'],
                'last_updated': r['last_updated']
            } for r in rows]

            return jsonify({'success': True, 'summaries': summaries})
        except Exception as e:
            logger.error(f"版本概览查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500