"""
admin_batch.py - 批量操作模块
提供批量任务的创建、状态查询、列表、取消、回滚和导出功能。

从 admin.py 拆分出来，独立管理批量操作相关路由。
"""
import json
import threading

from flask import request, jsonify, session
from routes.shared import (
    get_db, login_required,
    _t, logger,
    BATCH_RESOURCE_TABLES,
    BATCH_ACTIONS,
    ACTIVE_BATCH_TASKS,
    _batch_audit,
    _execute_batch_task,
    _rollback_batch_task,
)


def register_batch_routes(bp):

    @bp.route('/api/batch', methods=['POST'])
    @login_required
    def api_batch_create():
        try:
            data = request.get_json(silent=True) or {}
            org_id = session.get('org_id')
            user_id = session.get('user_id')

            resource_type = (data.get('resource_type') or '').strip()
            task_type = (data.get('task_type') or '').strip()
            resource_ids = data.get('resource_ids', [])

            if resource_type not in BATCH_RESOURCE_TABLES:
                return jsonify({'error': f'不支持的资源类型: {resource_type}'}), 400
            if task_type not in BATCH_ACTIONS:
                return jsonify({'error': f'不支持的操作: {task_type}'}), 400
            if not resource_ids or not isinstance(resource_ids, list):
                return jsonify({'error': _t('error.selectAtLeastOne', '请选择至少一个资源')}), 400
            if len(resource_ids) > 10000:
                return jsonify({'error': _t('error.batchLimit', '单次最多操作10000条数据')}), 400

            params = {
                'resource_ids': resource_ids,
                'updates': data.get('updates', {}),
                'target_state': data.get('target_state', 1),
                'tag': data.get('tag', ''),
                'permission': data.get('permission', ''),
                'max_retries': data.get('max_retries', 3),
                'retry_count': 0,
            }

            with get_db() as conn:
                c = conn.cursor()
                c.execute('''INSERT INTO batch_tasks (org_id, user_id, task_type, resource_type, params_json)
                            VALUES (?,?,?,?,?)''', (org_id, user_id, task_type, resource_type, json.dumps(params)))
                conn.commit()
                task_id = c.lastrowid

            _batch_audit(org_id, user_id, task_id, 'batch_start', resource_type, 0,
                        f'批量{task_type}: {len(resource_ids)}条')

            ACTIVE_BATCH_TASKS[task_id] = {'cancelled': False}
            thread = threading.Thread(target=_execute_batch_task, args=(task_id,), daemon=True)
            thread.start()

            return jsonify({'success': True, 'task_id': task_id, 'message': '批量任务已创建'})
        except Exception as e:
            logger.error(f"创建批量任务失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.createTaskFailed', '创建任务失败')}), 500

    @bp.route('/api/batch/<int:task_id>', methods=['GET'])
    @login_required
    def api_batch_status(task_id):
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM batch_tasks WHERE id=? AND org_id=?', (task_id, org_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': _t('error.taskNotFound', '任务不存在')}), 404

                task = dict(row)
                progress = 0
                if task['total_count'] > 0:
                    processed = task['success_count'] + task['fail_count']
                    progress = round(processed / task['total_count'] * 100, 1)

                c.execute('''SELECT * FROM batch_task_items WHERE task_id=?
                            ORDER BY id LIMIT 100''', (task_id,))
                items = [dict(r) for r in c.fetchall()]

            return jsonify({
                'success': True,
                'task': {
                    'id': task['id'], 'task_type': task['task_type'],
                    'resource_type': task['resource_type'],
                    'status': task['status'], 'total_count': task['total_count'],
                    'success_count': task['success_count'], 'fail_count': task['fail_count'],
                    'skip_count': task['skip_count'], 'error_msg': task['error_msg'],
                    'progress': progress,
                    'created_at': task['created_at'], 'started_at': task['started_at'],
                    'completed_at': task['completed_at']
                },
                'items': items
            })
        except Exception as e:
            logger.error(f"查询批量任务失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed')}), 500

    @bp.route('/api/batch', methods=['GET'])
    @login_required
    def api_batch_list():
        try:
            org_id = session.get('org_id')
            status = (request.args.get('status') or '').strip()
            page = max(1, int(request.args.get('page', 1) or 1))
            size = min(50, max(1, int(request.args.get('size', 20) or 20)))

            with get_db() as conn:
                c = conn.cursor()
                where = 'WHERE org_id=?'
                params = [org_id]
                if status:
                    where += ' AND status=?'
                    params.append(status)

                c.execute(f'SELECT COUNT(*) FROM batch_tasks {where}', params)
                total = c.fetchone()[0]

                offset = (page - 1) * size
                c.execute(f'SELECT * FROM batch_tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
                         params + [size, offset])
                rows = c.fetchall()

            tasks = []
            for r in rows:
                task = dict(r)
                progress = 0
                if task['total_count'] > 0:
                    processed = task['success_count'] + task['fail_count']
                    progress = round(processed / task['total_count'] * 100, 1)
                tasks.append({
                    'id': task['id'], 'task_type': task['task_type'],
                    'task_type_label': BATCH_ACTIONS.get(task['task_type'], {}).get('label', task['task_type']),
                    'task_type_icon': BATCH_ACTIONS.get(task['task_type'], {}).get('icon', '📋'),
                    'task_type_color': BATCH_ACTIONS.get(task['task_type'], {}).get('color', '#6366F1'),
                    'resource_type': task['resource_type'],
                    'status': task['status'], 'total_count': task['total_count'],
                    'success_count': task['success_count'], 'fail_count': task['fail_count'],
                    'progress': progress,
                    'created_at': task['created_at'], 'completed_at': task['completed_at']
                })

            return jsonify({'success': True, 'total': total, 'page': page, 'size': size,
                           'total_pages': max(1, (total + size - 1) // size), 'tasks': tasks})
        except Exception as e:
            logger.error(f"批量任务列表查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/batch/<int:task_id>/cancel', methods=['POST'])
    @login_required
    def api_batch_cancel(task_id):
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM batch_tasks WHERE id=? AND org_id=?', (task_id, org_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': _t('error.taskNotFound', '任务不存在')}), 404
                if row['status'] not in ('pending', 'running'):
                    return jsonify({'error': _t('error.taskCannotBeCancelled', '任务状态不允许取消')}), 400

            if task_id in ACTIVE_BATCH_TASKS:
                ACTIVE_BATCH_TASKS[task_id]['cancelled'] = True
            else:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute('UPDATE batch_tasks SET status=? WHERE id=?', ('cancelled', task_id))
                    conn.commit()

            return jsonify({'success': True, 'message': '任务已取消'})
        except Exception as e:
            logger.error(f"取消批量任务失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.cancelFailed', '取消失败')}), 500

    @bp.route('/api/batch/<int:task_id>/rollback', methods=['POST'])
    @login_required
    def api_batch_rollback(task_id):
        try:
            org_id = session.get('org_id')

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM batch_tasks WHERE id=? AND org_id=?', (task_id, org_id))
                row = c.fetchone()
                if not row:
                    return jsonify({'error': _t('error.taskNotFound', '任务不存在')}), 404
                if row['status'] != 'completed':
                    return jsonify({'error': _t('error.onlyCompletedTaskCanRollback', '只能回滚已完成的任务')}), 400
                if not BATCH_ACTIONS.get(row['task_type'], {}).get('reversible'):
                    return jsonify({'error': _t('error.rollbackNotSupported', '该操作类型不支持回滚')}), 400

            rolled, failed = _rollback_batch_task(task_id)
            return jsonify({'success': True, 'rolled': rolled, 'failed': failed,
                           'message': f'回滚完成: {rolled}条成功, {failed}条失败'})
        except Exception as e:
            logger.error(f"回滚失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.rollbackFailed', '回滚失败')}), 500

    @bp.route('/api/batch/<int:task_id>/export', methods=['GET'])
    @login_required
    def api_batch_export(task_id):
        try:
            org_id = session.get('org_id')
            page = max(1, int(request.args.get('page', 1) or 1))
            size = min(200, max(1, int(request.args.get('size', 50) or 50)))

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM batch_tasks WHERE id=? AND org_id=?', (task_id, org_id))
                task = c.fetchone()
                if not task:
                    return jsonify({'error': _t('error.taskNotFound', '任务不存在')}), 404

                c.execute('SELECT COUNT(*) FROM batch_task_items WHERE task_id=?', (task_id,))
                total = c.fetchone()[0]

                offset = (page - 1) * size
                c.execute('SELECT * FROM batch_task_items WHERE task_id=? ORDER BY id LIMIT ? OFFSET ?',
                         (task_id, size, offset))
                items = c.fetchall()

            items_data = [{
                'id': item['id'], 'resource_id': item['resource_id'],
                'resource_type': item['resource_type'], 'title': item['title'],
                'action': item['action'], 'status': item['status'],
                'error_msg': item['error_msg'] or '', 'processed_at': item['processed_at'] or ''
            } for item in items]

            return jsonify({
                'success': True, 'total': total, 'page': page, 'size': size,
                'total_pages': max(1, (total + size - 1) // size), 'items': items_data
            })
        except Exception as e:
            logger.error(f"导出失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.exportFailed', '导出失败')}), 500

    @bp.route('/api/batch/audit', methods=['GET'])
    @login_required
    def api_batch_audit():
        try:
            org_id = session.get('org_id')
            task_id = (request.args.get('task_id') or '').strip()
            page = max(1, int(request.args.get('page', 1) or 1))
            size = min(100, max(1, int(request.args.get('size', 50) or 50)))

            with get_db() as conn:
                c = conn.cursor()
                where = 'WHERE org_id=?'
                params = [org_id]
                if task_id:
                    where += ' AND task_id=?'
                    params.append(int(task_id))

                c.execute(f'SELECT COUNT(*) FROM batch_audit_log {where}', params)
                total = c.fetchone()[0]

                offset = (page - 1) * size
                c.execute(f'SELECT * FROM batch_audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
                         params + [size, offset])
                rows = c.fetchall()

            logs = [{
                'id': r['id'], 'user_id': r['user_id'], 'task_id': r['task_id'],
                'action': r['action'], 'resource_type': r['resource_type'],
                'resource_id': r['resource_id'], 'detail': r['detail'],
                'created_at': r['created_at']
            } for r in rows]

            return jsonify({'success': True, 'total': total, 'page': page, 'size': size,
                           'total_pages': max(1, (total + size - 1) // size), 'logs': logs})
        except Exception as e:
            logger.error(f"审计日志查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500