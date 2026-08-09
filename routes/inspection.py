"""
inspection.py - 巡检系统模块
负责资产的定期巡检计划和记录管理。

巡检系统是资产管理的核心配套功能，确保资产得到定期检查和维护。
常见场景：消防设备巡检、电梯维保检查、设备运行状态检查等。

主要功能：
1. 巡检计划：创建定期巡检计划（按天/周/月）
2. 巡检记录：提交巡检结果（正常/异常）
3. 逾期检测：自动检测逾期未巡检的资产
4. 异常处理：巡检异常时自动创建工单

关键概念：
- 巡检计划（Inspection Plan）：定义巡检频率（如每7天一次）
- 巡检记录（Inspection Record）：每次巡检的结果记录
- 逾期（Overdue）：超过巡检周期未完成巡检
- 自动工单：巡检异常时自动创建维修工单
"""
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, check_quota,
    workflow_trigger_after_inspection
)
from routes.workflow_engine import (
    workflow_trigger_after_workorder_create
)

inspection_bp = Blueprint('inspection', __name__)


@inspection_bp.route('/api/inspection/plans', methods=['GET'])
@require_permission('inspection:view')
def list_inspection_plans():
    """巡检计划列表"""
    try:
        org_id = session.get('org_id')
        today = datetime.now().date()
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT ip.*, a.name as asset_name, a.asset_code
                        FROM inspection_plans ip LEFT JOIN assets a ON ip.asset_id = a.id
                        WHERE ip.org_id=? AND ip.is_active=1 AND ip.is_deleted=0
                        ORDER BY ip.created_at DESC''', (org_id,))
            rows = c.fetchall()
        
        plans = []
        for r in rows:
            next_due = None
            is_overdue = False
            if r['last_completed']:
                try:
                    last_dt = datetime.strptime(r['last_completed'][:10], '%Y-%m-%d').date()
                    next_due = last_dt + timedelta(days=r['frequency_days'])
                    is_overdue = next_due < today
                    next_due = next_due.strftime('%Y-%m-%d')
                except:
                    next_due = None
            else:
                is_overdue = True
                next_due = '未巡检'
            
            plans.append({
                'id': r['id'], 'qrcode_id': r['qrcode_id'], 'asset_id': r['asset_id'],
                'asset_name': r['asset_name'], 'cycle_type': r['cycle_type'],
                'frequency_days': r['frequency_days'], 'assigned_user_id': r['assigned_user_id'],
                'last_completed': r['last_completed'], 'next_due': next_due,
                'is_overdue': is_overdue, 'created_at': r['created_at']
            })
        
        return jsonify({'success': True, 'plans': plans})
    except Exception as e:
        logger.error(f"巡检计划列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@inspection_bp.route('/api/inspection/plans', methods=['POST'])
@require_permission('inspection:view')
def create_inspection_plan():
    """创建巡检计划"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        qrcode_id = data.get('qrcode_id')
        asset_id = data.get('asset_id')
        cycle_type = data.get('cycle_type', 'weekly')
        frequency_days = int(data.get('frequency_days', 7) or 7)
        assigned_user_id = data.get('assigned_user_id')
        
        with get_db() as conn:
            c = conn.cursor()
            if asset_id:
                c.execute('SELECT id FROM assets WHERE id=? AND org_id=?', (asset_id, org_id))
                if not c.fetchone():
                    return jsonify({'error': _t('error.assetNotFound')}), 404
            
            c.execute('''INSERT INTO inspection_plans
                        (org_id, qrcode_id, asset_id, cycle_type, frequency_days, assigned_user_id)
                        VALUES (?,?,?,?,?,?)''',
                     (org_id, qrcode_id, asset_id, cycle_type, frequency_days, assigned_user_id))
            plan_id = c.lastrowid
            conn.commit()
        
        log_action('create_plan', 'inspection_plan', plan_id)
        return jsonify({'success': True, 'plan_id': plan_id})
    except Exception as e:
        logger.error(f"创建巡检计划失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@inspection_bp.route('/api/inspection/plans/<int:plan_id>', methods=['PUT'])
@require_permission('inspection:view')
def update_inspection_plan(plan_id):
    """更新巡检计划"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        cycle_type = data.get('cycle_type')
        frequency_days = int(data.get('frequency_days', 0) or 0)
        assigned_user_id = data.get('assigned_user_id')
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM inspection_plans WHERE id=? AND org_id=?', (plan_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.planNotFound')}), 404
            
            updates = []
            params = []
            if cycle_type:
                updates.append('cycle_type = ?')
                params.append(cycle_type)
            if frequency_days > 0:
                updates.append('frequency_days = ?')
                params.append(frequency_days)
            if assigned_user_id is not None:
                updates.append('assigned_user_id = ?')
                params.append(assigned_user_id)
            
            params.extend([plan_id, org_id])
            sql = f'UPDATE inspection_plans SET {", ".join(updates)} WHERE id=? AND org_id=?'
            c.execute(sql, params)
            conn.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"更新巡检计划失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500



@inspection_bp.route('/api/inspection/plans/<int:plan_id>/disable', methods=['POST'])
@require_permission('inspection:view')
def disable_inspection_plan(plan_id):
    """停用巡检计划"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM inspection_plans WHERE id=? AND org_id=?', (plan_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.planNotFound')}), 404
            
            c.execute('UPDATE inspection_plans SET is_active=0 WHERE id=? AND org_id=?', (plan_id, org_id))
            conn.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"停用巡检计划失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500



@inspection_bp.route('/api/inspection/records', methods=['POST'])
@require_permission('inspection:submit')
def submit_inspection():
    """提交巡检记录
    
    这是巡检系统的核心功能。巡检人员扫描资产上的二维码后，
    填写巡检结果并提交。系统会自动处理异常情况。
    
    正常流程：
    1. 巡检人员扫码 → 填写结果 → 提交
    2. 更新计划的最后完成时间
    3. 触发工作流（如果有配置）
    
    异常处理（巡检结果不是 normal 时）：
    1. 自动创建一个高优先级的维修工单
    2. 工单标题：巡检异常：{资产名称}
    3. 触发工作流，通知相关人员
    """
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        inspector_id = session.get('user_id')
        qrcode_id = data.get('qrcode_id')
        plan_id = data.get('plan_id')
        asset_id = data.get('asset_id')
        result = data.get('result', 'normal')
        note = data.get('note', '') or ''
        images = data.get('images', []) or []
        gps_location = data.get('gps_location', '') or ''

        passed, limit, used, msg = check_quota(org_id, 'max_inspections')
        if not passed:
            return jsonify({'error': msg, 'quota_key': 'max_inspections', 'limit': limit, 'used': used}), 403
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO inspection_records
                        (plan_id, org_id, qrcode_id, asset_id, inspector_id,
                        result, note, images, gps_location)
                        VALUES (?,?,?,?,?,?,?,?,?)''',
                     (plan_id, org_id, qrcode_id, asset_id, inspector_id,
                      result, note, json.dumps(images) if images else None, gps_location))
            record_id = c.lastrowid
            
            if plan_id:
                c.execute('UPDATE inspection_plans SET last_completed=CURRENT_TIMESTAMP WHERE id=?', (plan_id,))
            
            auto_workorder_id = None
            if result != 'normal' and asset_id:
                # 巡检异常，自动创建工单
                c.execute('SELECT name FROM assets WHERE id=?', (asset_id,))
                asset = c.fetchone()
                asset_name = asset['name'] if asset else '未知资产'
                title = f"巡检异常：{asset_name}"
                c.execute('''INSERT INTO workorders
                            (org_id, qrcode_id, asset_id, title, description,
                            status, priority, created_by, created_at)
                            VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',
                         (org_id, qrcode_id, asset_id, title, note, 'open', 'high', inspector_id))
                auto_workorder_id = c.lastrowid
            
            conn.commit()
        
        if auto_workorder_id:
            log_action('auto_create_workorder', 'workorder', auto_workorder_id, {'reason': 'inspection_abnormal'})
            workflow_trigger_after_workorder_create(auto_workorder_id, org_id, title, 'high', inspector_id)
        log_action('submit_inspection', 'inspection_record', record_id)

        workflow_trigger_after_inspection(record_id, org_id, result, inspector_id, note)
        return jsonify({'success': True, 'record_id': record_id, 'auto_workorder_id': auto_workorder_id})
    except Exception as e:
        logger.error(f"提交巡检记录失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.submitFailed', '提交失败')}), 500



@inspection_bp.route('/api/inspection/records', methods=['GET'])
@require_permission('inspection:view')
def list_inspection_records():
    """巡检记录列表"""
    try:
        org_id = session.get('org_id')
        page = int(request.args.get('page', 1) or 1)
        size = int(request.args.get('size', 20) or 20)
        qrcode_id = request.args.get('qrcode_id')
        plan_id = request.args.get('plan_id')
        asset_id = request.args.get('asset_id')
        result = (request.args.get('result') or '').strip()
        
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE ir.org_id=?'
            params = [org_id]
            if qrcode_id:
                where += ' AND ir.qrcode_id=?'
                params.append(int(qrcode_id))
            if plan_id:
                where += ' AND ir.plan_id=?'
                params.append(int(plan_id))
            if asset_id:
                where += ' AND ir.asset_id=?'
                params.append(int(asset_id))
            if result:
                where += ' AND ir.result=?'
                params.append(result)
            
            c.execute(f'SELECT COUNT(*) FROM inspection_records ir {where}', params)
            total = c.fetchone()[0]
            
            offset = (page - 1) * size
            c.execute(f'''SELECT ir.*, a.name as asset_name, u.username as inspector_name
                        FROM inspection_records ir
                        LEFT JOIN assets a ON ir.asset_id = a.id
                        LEFT JOIN users u ON ir.inspector_id = u.id
                        {where} ORDER BY ir.inspected_at DESC LIMIT ? OFFSET ?''',
                     params + [size, offset])
            rows = c.fetchall()
        
        records = [{
            'id': r['id'], 'plan_id': r['plan_id'], 'asset_id': r['asset_id'],
            'asset_name': r['asset_name'], 'inspector_id': r['inspector_id'],
            'inspector_name': r['inspector_name'], 'result': r['result'],
            'note': r['note'], 'gps_location': r['gps_location'],
            'inspected_at': r['inspected_at']
        } for r in rows]
        
        return jsonify({'success': True, 'total': total, 'records': records})
    except Exception as e:
        logger.error(f"巡检记录列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@inspection_bp.route('/api/inspection/overdue', methods=['GET'])
@require_permission('inspection:view')
def list_overdue_inspections():
    """逾期巡检列表"""
    try:
        org_id = session.get('org_id')
        today = datetime.now().date()
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT ip.*, a.name as asset_name
                        FROM inspection_plans ip LEFT JOIN assets a ON ip.asset_id = a.id
                        WHERE ip.org_id=? AND ip.is_active=1''', (org_id,))
            rows = c.fetchall()
        
        overdue_plans = []
        for r in rows:
            if not r['last_completed']:
                days_overdue = (today - datetime.strptime(r['created_at'][:10], '%Y-%m-%d').date()).days
                overdue_plans.append({**dict(r), 'asset_name': r['asset_name'], 'days_overdue': days_overdue})
            else:
                try:
                    last_dt = datetime.strptime(r['last_completed'][:10], '%Y-%m-%d').date()
                    next_due = last_dt + timedelta(days=r['frequency_days'])
                    if next_due < today:
                        days_overdue = (today - next_due).days
                        overdue_plans.append({**dict(r), 'asset_name': r['asset_name'], 'days_overdue': days_overdue})
                except:
                    pass
        
        return jsonify({'success': True, 'count': len(overdue_plans), 'plans': overdue_plans})
    except Exception as e:
        logger.error(f"逾期查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


# ============ 工单系统 API ============