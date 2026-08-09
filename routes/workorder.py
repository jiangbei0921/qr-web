
"""jixu1
workorder.py - 工单系统模块
工单是用于跟踪和管理任务的标准流程，从创建到解决形成闭环。

主要功能：
1. 创建工单：提交问题或任务
2. 分配工单：将工单分配给具体的处理人员
3. 处理工单：更新工单状态和内容
4. 解决工单：标记问题已解决
5. 关闭工单：最终确认并关闭

工单状态流转：
open（待处理）→ processing（处理中）→ resolved（已解决）→ closed（已关闭）

优先级：
urgent（紧急）→ high（高）→ normal（普通）→ low（低）

关联关系：
- 工单可以关联到资产（asset_id）
- 工单可以关联到二维码（qrcode_id）
- 巡检异常时自动创建工单
"""
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, check_quota,
    update_org_quota,
    workflow_trigger_after_workorder_status
)
from routes.workflow_engine import (
    workflow_trigger_after_workorder_create
)

workorder_bp = Blueprint('workorder', __name__)


@workorder_bp.route('/api/workorders', methods=['GET'])
@require_permission('workorder:view')
def list_workorders():
    """工单列表"""
    try:
        org_id = session.get('org_id')
        page = int(request.args.get('page', 1) or 1)
        size = int(request.args.get('size', 20) or 20)
        status = (request.args.get('status') or '').strip()
        priority = (request.args.get('priority') or '').strip()
        assignee_id = request.args.get('assignee_id')
        asset_id = request.args.get('asset_id')
        
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE w.org_id=? AND w.is_deleted=0'
            params = [org_id]
            if status:
                where += ' AND w.status=?'
                params.append(status)
            if priority:
                where += ' AND w.priority=?'
                params.append(priority)
            if assignee_id:
                where += ' AND w.assignee_id=?'
                params.append(int(assignee_id))
            if asset_id:
                where += ' AND w.asset_id=?'
                params.append(int(asset_id))
            
            c.execute(f'SELECT COUNT(*) FROM workorders w {where}', params)
            total = c.fetchone()[0]
            
            offset = (page - 1) * size
            c.execute(f'''SELECT w.*, u.username as assignee_username, a.name as asset_name
                        FROM workorders w
                        LEFT JOIN users u ON w.assignee_id = u.id
                        LEFT JOIN assets a ON w.asset_id = a.id
                        {where} ORDER BY w.created_at DESC LIMIT ? OFFSET ?''',
                     params + [size, offset])
            rows = c.fetchall()
        
        workorders = [{
            'id': r['id'], 'title': r['title'], 'description': r['description'],
            'status': r['status'], 'priority': r['priority'], 'assignee_id': r['assignee_id'],
            'assignee_username': r['assignee_username'], 'asset_id': r['asset_id'],
            'asset_name': r['asset_name'], 'qrcode_id': r['qrcode_id'],
            'created_at': r['created_at'], 'updated_at': r['updated_at'],
            'resolved_at': r['resolved_at']
        } for r in rows]
        
        return jsonify({'success': True, 'total': total, 'workorders': workorders})
    except Exception as e:
        logger.error(f"工单列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed')}), 500



@workorder_bp.route('/api/workorders', methods=['POST'])
@require_permission('workorder:create')
def create_workorder():
    """创建工单
    
    工单创建流程：
    1. 检查配额（是否超过最大工单数量限制）
    2. 验证必填字段（标题）
    3. 创建工单记录，初始状态为 open（待处理）
    4. 触发工作流（如果有配置的话）
    5. 更新配额使用量
    
    工单可以关联：
    - 二维码（qrcode_id）：通过扫码创建工单
    - 资产（asset_id）：为特定资产创建维修工单
    - 处理人（assignee_id）：指定谁来处理
    """
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        title = (data.get('title') or '').strip()

        passed, limit, used, msg = check_quota(org_id, 'max_workorders')
        if not passed:
            return jsonify({'error': msg, 'quota': {'limit': limit, 'used': used}, 'upgrade_url': '/#subscription'}), 403
        description = data.get('description', '') or ''
        qrcode_id = data.get('qrcode_id')
        asset_id = data.get('asset_id')
        priority = data.get('priority', 'normal')
        assignee_id = data.get('assignee_id')
        images = data.get('images', []) or []
        
        if not title:
            return jsonify({'error': _t('error.workorderTitleRequired', '工单标题不能为空')}), 400
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO workorders
                        (org_id, title, description, qrcode_id, asset_id,
                        status, priority, assignee_id, created_by, images,
                        created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)''',
                     (org_id, title, description, qrcode_id, asset_id,
                      'open', priority, assignee_id, user_id,
                      json.dumps(images) if images else None))
            workorder_id = c.lastrowid
            conn.commit()
        
        log_action('create_workorder', 'workorder', workorder_id)
        workflow_trigger_after_workorder_create(workorder_id, org_id, title, priority, user_id)
        update_org_quota(org_id, 'max_workorders', 1)
        return jsonify({'success': True, 'workorder_id': workorder_id})
    except Exception as e:
        logger.error(f"创建工单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createFailed')}), 500



@workorder_bp.route('/api/workorders/<int:workorder_id>', methods=['GET'])
@require_permission('workorder:view')
def get_workorder_detail(workorder_id):
    """工单详情"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT w.*, u.username as assignee_username, a.name as asset_name
                        FROM workorders w
                        LEFT JOIN users u ON w.assignee_id = u.id
                        LEFT JOIN assets a ON w.asset_id = a.id
                        WHERE w.id=? AND w.org_id=?''', (workorder_id, org_id))
            w = c.fetchone()
            if not w:
                return jsonify({'error': _t('error.workorderNotFound', '工单不存在')}), 404
            
            asset = None
            if w['asset_id']:
                c.execute('SELECT * FROM assets WHERE id=?', (w['asset_id'],))
                asset = c.fetchone()
            
            c.execute('SELECT * FROM audit_logs WHERE target_type=? AND target_id=? ORDER BY created_at DESC',
                     ('workorder', workorder_id))
            logs = [dict(r) for r in c.fetchall()]
        
        inspection_record = None
        if w['asset_id']:
            with get_db() as conn:
                c = conn.cursor()
                c.execute('''SELECT * FROM inspection_records WHERE asset_id=? ORDER BY inspected_at DESC LIMIT 1''',
                         (w['asset_id'],))
                inspection_record = c.fetchone()
        
        return jsonify({
            'success': True,
            'workorder': dict(w),
            'asset': dict(asset) if asset else None,
            'last_inspection': dict(inspection_record) if inspection_record else None,
            'logs': logs
        })
    except Exception as e:
        logger.error(f"工单详情查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workorder_bp.route('/api/workorders/<int:workorder_id>', methods=['PUT'])
@require_permission('workorder:manage')
def update_workorder(workorder_id):
    """更新工单"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        title = data.get('title')
        description = data.get('description')
        priority = data.get('priority')
        assignee_id = data.get('assignee_id')
        status = data.get('status')
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, status FROM workorders WHERE id=? AND org_id=?', (workorder_id, org_id))
            wf = c.fetchone()
            if not wf:
                return jsonify({'error': _t('error.workorderNotFound')}), 404
            old_status = wf['status']
            
            updates = []
            params = []
            if title is not None:
                updates.append('title = ?')
                params.append(title)
            if description is not None:
                updates.append('description = ?')
                params.append(description)
            if priority is not None:
                updates.append('priority = ?')
                params.append(priority)
            if assignee_id is not None:
                updates.append('assignee_id = ?')
                params.append(assignee_id)
            if status is not None:
                updates.append('status = ?')
                params.append(status)
            
            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.extend([workorder_id, org_id])
            sql = f'UPDATE workorders SET {", ".join(updates)} WHERE id=? AND org_id=?'
            c.execute(sql, params)
            conn.commit()
            
            if status is not None and status != old_status:
                workflow_trigger_after_workorder_status(workorder_id, org_id, old_status, status)
        
        log_action('update_workorder', 'workorder', workorder_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"更新工单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500



@workorder_bp.route('/api/workorders/<int:workorder_id>/assign', methods=['POST'])
@require_permission('workorder:manage')
def assign_workorder(workorder_id):
    """分配工单"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        assignee_id = data.get('assignee_id')
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, status FROM workorders WHERE id=? AND org_id=?', (workorder_id, org_id))
            wo = c.fetchone()
            if not wo:
                return jsonify({'error': _t('error.workorderNotFound', '工单不存在')}), 404
            old_status = wo['status']
            
            c.execute('SELECT id FROM users WHERE id=? AND org_id=? AND is_active=1', (assignee_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.assigneeNotFound')}), 404
            
            c.execute('''UPDATE workorders SET assignee_id=?, status=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND org_id=?''', (assignee_id, 'processing', workorder_id, org_id))
            conn.commit()
        
        workflow_trigger_after_workorder_status(workorder_id, org_id, old_status, 'processing')
        log_action('assign_workorder', 'workorder', workorder_id, {'assignee_id': assignee_id})
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"分配工单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.assignFailed', '分配失败')}), 500



@workorder_bp.route('/api/workorders/<int:workorder_id>/resolve', methods=['POST'])
@require_permission('workorder:manage')
def resolve_workorder(workorder_id):
    """解决工单"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        resolution_note = data.get('resolution_note', '') or ''
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, status, asset_id FROM workorders WHERE id=? AND org_id=?', (workorder_id, org_id))
            w = c.fetchone()
            if not w:
                return jsonify({'error': _t('error.workorderNotFound')}), 404
            old_status = w['status']
            
            c.execute('''UPDATE workorders SET status=?, resolution_note=?,
                        resolved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND org_id=?''',
                     ('resolved', resolution_note, workorder_id, org_id))
            
            if w['asset_id']:
                c.execute('UPDATE assets SET status=? WHERE id=?', ('normal', w['asset_id']))
            
            conn.commit()
        
        workflow_trigger_after_workorder_status(workorder_id, org_id, old_status, 'resolved')
        log_action('resolve_workorder', 'workorder', workorder_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"解决工单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500



@workorder_bp.route('/api/workorders/<int:workorder_id>/close', methods=['POST'])
@require_permission('workorder:manage')
def close_workorder(workorder_id):
    """关闭工单"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, status FROM workorders WHERE id=? AND org_id=?', (workorder_id, org_id))
            wo = c.fetchone()
            if not wo:
                return jsonify({'error': _t('error.workorderNotFound', '工单不存在')}), 404
            old_status = wo['status']
            
            c.execute('UPDATE workorders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND org_id=?',
                     ('closed', workorder_id, org_id))
            conn.commit()
        
        workflow_trigger_after_workorder_status(workorder_id, org_id, old_status, 'closed')
        log_action('close_workorder', 'workorder', workorder_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"关闭工单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.closeFailed', '关闭失败')}), 500



@workorder_bp.route('/api/workorders/stats', methods=['GET'])
@require_permission('workorder:view')
def workorder_stats():
    """工单统计"""
    try:
        org_id = session.get('org_id')
        today = datetime.now().strftime('%Y-%m-%d')
        with get_db() as conn:
            c = conn.cursor()
            stats = {}
            for status in ['open', 'processing', 'resolved', 'closed']:
                c.execute('SELECT COUNT(*) FROM workorders WHERE org_id=? AND status=?', (org_id, status))
                stats[status] = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM workorders WHERE org_id=? AND status=? AND julianday(CURRENT_TIMESTAMP) - julianday(created_at) > 3',
                     (org_id, 'open'))
            stats['overdue'] = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM workorders WHERE org_id=? AND date(created_at) = ?', (org_id, today))
            stats['today_created'] = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM workorders WHERE org_id=? AND priority=? AND status != ?',
                     (org_id, 'urgent', 'closed'))
            stats['urgent'] = c.fetchone()[0]
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"工单统计查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


# ============ 工作台 API ============