"""
workflow.py - 工作流引擎模块
可视化的工作流自动化引擎，支持拖拽式编辑和事件驱动执行。

工作流是系统的"自动化大脑"，当特定事件发生时（如扫码、创建工单），
自动执行预设的一系列动作。

主要功能：
1. 工作流定义：创建和管理工作流（名称、触发器、动作）
2. 版本管理：保存工作流的不同版本，支持回滚
3. 节点编辑：可视化编辑工作流节点和连线
4. 手动触发：支持手动执行工作流
5. 执行实例：查看工作流的执行历史和日志
6. Webhook接收：通过Webhook接收外部事件触发工作流

工作流组成：
- 触发器（Trigger）：定义工作流何时启动（如扫码、表单提交、定时）
- 节点（Node）：工作流中的每个步骤（如发送通知、创建工单、修改数据）
- 边（Edge）：节点之间的连线，定义了执行顺序和条件
- 执行实例（Instance）：工作流每次运行的具体实例
"""
import json
import uuid
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, check_quota,
    update_org_quota, get_org_quota, parse_pagination,
    get_org_subscription
)
from routes.workflow_engine import workflow_trigger_schedule_poll

workflow_bp = Blueprint('workflow', __name__)


def _get_engine():
    """延迟导入工作流引擎，避免循环引用"""
    from routes.workflow_engine import WorkflowEngine, TRIGGER_TYPES, ACTION_TYPES
    return WorkflowEngine, TRIGGER_TYPES, ACTION_TYPES


@workflow_bp.route('/api/workflow/definitions', methods=['GET'])
@require_permission('user:manage')
def api_workflow_list():
    """获取工作流定义列表"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id, name, description, trigger_type, trigger_config, current_version, is_enabled, created_at, updated_at '
                'FROM workflow_definitions WHERE org_id=? AND is_deleted=0 ORDER BY updated_at DESC',
                (org_id,)
            )
            wfs = [dict(r) for r in c.fetchall()]
        _, trigger_types, action_types = _get_engine()
        return jsonify({'success': True, 'data': {'workflows': wfs, 'trigger_types': trigger_types, 'action_types': action_types}})
    except Exception as e:
        logger.error(f"工作流列表查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workflow_bp.route('/api/workflow/definitions', methods=['POST'])
@require_permission('user:manage')
def api_workflow_create():
    """创建工作流定义"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': _t('error.workflowNameRequired')}), 400
        trigger_type = (data.get('trigger_type') or '').strip()
        _, trigger_types, _ = _get_engine()
        if trigger_type not in trigger_types:
            return jsonify({'error': f'无效的触发器类型: {trigger_type}'}), 400

        description = (data.get('description') or '').strip()
        trigger_config = json.dumps(data.get('trigger_config', {}), ensure_ascii=False)

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO workflow_definitions (org_id, name, description, trigger_type, trigger_config, created_by) '
                'VALUES (?,?,?,?,?,?)',
                (org_id, name, description, trigger_type, trigger_config, user_id)
            )
            wf_id = c.lastrowid
            # 创建初始版本（空图）
            c.execute(
                'INSERT INTO workflow_versions (workflow_id, version, nodes_json, edges_json, created_by) VALUES (?,?,?,?,?)',
                (wf_id, 1, '[]', '[]', user_id)
            )
            conn.commit()

        log_action('workflow_created', 'workflow', wf_id, detail={'name': name, 'trigger_type': trigger_type})
        return jsonify({'success': True, 'data': {'id': wf_id}})
    except Exception as e:
        logger.error(f"创建工作流失败: {e}")
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@workflow_bp.route('/api/workflow/definitions/<int:wf_id>', methods=['PUT'])
@require_permission('user:manage')
def api_workflow_update(wf_id):
    """更新工作流定义"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        updates = {}
        for field in ['name', 'description', 'trigger_type', 'trigger_config', 'is_enabled']:
            if field in data:
                if field == 'trigger_config' and isinstance(data[field], (dict, list)):
                    updates[field] = json.dumps(data[field], ensure_ascii=False)
                elif field == 'is_enabled':
                    updates[field] = 1 if data[field] else 0
                else:
                    updates[field] = (data[field] or '').strip() if isinstance(data[field], str) else data[field]

        if not updates:
            return jsonify({'error': _t('error.noValidUpdateFields', '无有效更新字段')}), 400
        updates['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM workflow_definitions WHERE id=? AND org_id=?', (wf_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.workflowNotFoundOrDisabled')}), 404
            set_clause = ', '.join(f'{k}=?' for k in updates)
            c.execute(
                f'UPDATE workflow_definitions SET {set_clause} WHERE id=? AND org_id=?',
                list(updates.values()) + [wf_id, org_id]
            )
            conn.commit()
        return jsonify({'success': True, 'data': updates})
    except Exception as e:
        logger.error(f"更新工作流失败: {e}")
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500



@workflow_bp.route('/api/workflow/definitions/<int:wf_id>', methods=['DELETE'])
@require_permission('user:manage')
def api_workflow_delete(wf_id):
    """软删除工作流"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE workflow_definitions SET is_deleted=1, updated_at=? WHERE id=? AND org_id=?',
                      (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), wf_id, org_id))
            conn.commit()
        log_action('workflow_deleted', 'workflow', wf_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除工作流失败: {e}")
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500



@workflow_bp.route('/api/workflow/definitions/<int:wf_id>/versions', methods=['GET'])
@require_permission('user:manage')
def api_workflow_get_versions(wf_id):
    """获取工作流版本列表"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM workflow_definitions WHERE id=? AND org_id=?', (wf_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.workflowNotFoundOrDisabled')}), 404
            c.execute('SELECT * FROM workflow_versions WHERE workflow_id=? ORDER BY version DESC', (wf_id,))
            versions = [dict(r) for r in c.fetchall()]
        return jsonify({'success': True, 'data': {'versions': versions}})
    except Exception as e:
        logger.error(f"版本查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workflow_bp.route('/api/workflow/definitions/<int:wf_id>/versions', methods=['POST'])
@require_permission('user:manage')
def api_workflow_save_version(wf_id):
    """保存新版本（保存编辑器中的节点和边）"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        data = request.get_json(silent=True) or {}
        nodes = data.get('nodes', [])
        edges = data.get('edges', [])

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM workflow_definitions WHERE id=? AND org_id=?', (wf_id, org_id))
            wf = c.fetchone()
            if not wf:
                return jsonify({'error': _t('error.workflowNotFound', '工作流不存在')}), 404

            new_version = wf['current_version'] + 1
            c.execute(
                'INSERT INTO workflow_versions (workflow_id, version, nodes_json, edges_json, created_by) VALUES (?,?,?,?,?)',
                (wf_id, new_version, json.dumps(nodes, ensure_ascii=False), json.dumps(edges, ensure_ascii=False), user_id)
            )
            c.execute('UPDATE workflow_definitions SET current_version=?, updated_at=? WHERE id=?',
                      (new_version, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), wf_id))
            conn.commit()

        log_action('workflow_version_saved', 'workflow', wf_id, detail={'version': new_version})
        return jsonify({'success': True, 'data': {'version': new_version}})
    except Exception as e:
        logger.error(f"保存版本失败: {e}")
        return jsonify({'error': _t('error.saveFailed', '保存失败')}), 500



@workflow_bp.route('/api/workflow/definitions/<int:wf_id>/execute', methods=['POST'])
@require_permission('user:manage')
def api_workflow_execute(wf_id):
    """手动触发执行工作流"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        trigger_event = data.get('trigger_event', {})
        trigger_event['manual'] = True
        engine, _, _ = _get_engine()
        result = engine.execute_workflow(wf_id, org_id, trigger_event)
        return jsonify(result)
    except Exception as e:
        logger.error(f"手动执行工作流失败: {e}", exc_info=True)
        return jsonify({
            'error': _t('error.serverError', '服务器错误，请稍后重试')
        }), 500



@workflow_bp.route('/api/workflow/instances', methods=['GET'])
@require_permission('user:manage')
def api_workflow_instances():
    """获取执行实例列表"""
    try:
        org_id = session.get('org_id')
        page, size, offset = parse_pagination(default_size=50, max_size=200)
        wf_id = request.args.get('workflow_id', '')
        status_filter = request.args.get('status', '')

        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE wi.org_id=?'
            params = [org_id]
            if wf_id:
                where += ' AND wi.workflow_id=?'
                params.append(int(wf_id))
            if status_filter:
                where += ' AND wi.status=?'
                params.append(status_filter)

            c.execute(f'SELECT COUNT(*) FROM workflow_instances wi {where}', params)
            total = c.fetchone()[0]

            c.execute(
                f'SELECT wi.*, wd.name as workflow_name FROM workflow_instances wi '
                f'LEFT JOIN workflow_definitions wd ON wi.workflow_id=wd.id '
                f'{where} ORDER BY wi.started_at DESC LIMIT ? OFFSET ?',
                params + [size, offset]
            )
            instances = [dict(r) for r in c.fetchall()]

        return jsonify({'success': True, 'data': {
            'instances': instances, 'total': total, 'page': page, 'size': size,
            'total_pages': max(1, (total + size - 1) // size)
        }})
    except Exception as e:
        logger.error(f"实例查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workflow_bp.route('/api/workflow/instances/<int:instance_id>/logs', methods=['GET'])
@require_permission('user:manage')
def api_workflow_instance_logs(instance_id):
    """获取实例执行日志"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM workflow_instances WHERE id=?', (instance_id,))
            instance = c.fetchone()
            if not instance:
                return jsonify({'error': _t('error.instanceNotFound', '实例不存在')}), 404

            c.execute(
                'SELECT * FROM workflow_execution_logs WHERE instance_id=? ORDER BY started_at',
                (instance_id,)
            )
            logs = [dict(r) for r in c.fetchall()]

        return jsonify({'success': True, 'data': {'instance': dict(instance), 'logs': logs}})
    except Exception as e:
        logger.error(f"日志查询失败: {e}")
        return jsonify({'error': _t('error.queryFailed')}), 500



@workflow_bp.route('/api/workflow/webhook/<path:webhook_path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def api_workflow_webhook(webhook_path):
    """Webhook接收端点"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id, org_id FROM workflow_definitions '
                'WHERE trigger_type=? AND is_enabled=1 AND is_deleted=0 '
                "AND trigger_config LIKE ?",
                ('webhook:received', f'%{webhook_path}%')
            )
            wfs = c.fetchall()

        results = []
        for wf in wfs:
            event = {
                'webhook_url': webhook_path,
                'method': request.method,
                'payload': request.get_json(silent=True) or request.get_data(as_text=True) or {},
                'received_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            engine, _, _ = _get_engine()
            result = engine.execute_workflow(wf['id'], wf['org_id'], event)
            results.append(result)

            with get_db() as conn:
                conn.cursor().execute(
                    'INSERT INTO workflow_webhook_logs (workflow_id, request_method, request_headers, request_body, response_status) '
                    'VALUES (?,?,?,?,?)',
                    (wf['id'], request.method, json.dumps(dict(request.headers), ensure_ascii=False, default=str),
                     json.dumps(event['payload'], ensure_ascii=False, default=str), 200)
                )
                conn.commit()

        return jsonify({'success': True, 'results': results})
    except Exception as e:
        logger.error(f"Webhook处理失败: {e}")
        return jsonify({'error': _t('error.processFailed', '处理失败')}), 500



@workflow_bp.route('/api/workflow/poll', methods=['POST'])
@require_permission('user:manage')
def api_workflow_poll():
    """手动触发定时轮询（schedule:time 和 workorder:overdue）"""
    try:
        results = workflow_trigger_schedule_poll()
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        logger.error(f"轮询触发器执行失败: {e}")
        return jsonify({'error': _t('error.pollFailed', '轮询失败')}), 500


def get_feature_enabled(org_id, feature_key):
    """检查组织是否开启了某项功能"""
    sub = get_org_subscription(org_id)
    if not sub:
        return False
    features = json.loads(sub['features_json'] or '{}')
    return bool(features.get(feature_key, False))


def sync_quota_usage(org_id):
    """同步所有配额使用量到 quota_usage 表"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as cnt FROM qrcodes WHERE org_id=?', (org_id,))
        update_org_quota(org_id, 'max_qrcodes', c.fetchone()['cnt'] - get_org_quota(org_id, 'max_qrcodes'))
        c.execute('SELECT COUNT(*) as cnt FROM users WHERE org_id=? AND is_active=1', (org_id,))
        update_org_quota(org_id, 'max_users', c.fetchone()['cnt'] - get_org_quota(org_id, 'max_users'))
        c.execute('SELECT COUNT(*) as cnt FROM forms WHERE org_id=?', (org_id,))
        update_org_quota(org_id, 'max_forms', c.fetchone()['cnt'] - get_org_quota(org_id, 'max_forms'))
        c.execute('SELECT COUNT(*) as cnt FROM workorders WHERE org_id=?', (org_id,))
        update_org_quota(org_id, 'max_workorders', c.fetchone()['cnt'] - get_org_quota(org_id, 'max_workorders'))
        c.execute('SELECT COUNT(*) as cnt FROM inspection_records WHERE org_id=?', (org_id,))
        update_org_quota(org_id, 'max_inspections', c.fetchone()['cnt'] - get_org_quota(org_id, 'max_inspections'))


def require_quota(quota_key):
    """配额校验装饰器"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            org_id = session.get('org_id')
            if not org_id:
                return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
            passed, limit, used, msg = check_quota(org_id, quota_key)
            if not passed:
                return jsonify({'error': msg, 'quota_key': quota_key, 'limit': limit, 'used': used}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


class PaymentGateway:
    """支付网关抽象层（模拟实现，接入真实支付只需替换此类）"""

    @staticmethod
    def create_order(org_id, plan_id, amount, currency='CNY', return_url=''):
        """创建支付订单，返回 (pay_url, txn_id)"""
        txn_id = 'SIM' + uuid.uuid4().hex[:16].upper()
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO billing_invoices (org_id, plan_id, amount, currency, status, invoice_type, payment_gateway_txn_id, billing_period_start, billing_period_end)
                        VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now','+30 days'))''',
                     (org_id, plan_id, amount, currency, 'pending', 'new_subscription', txn_id))
            invoice_id = c.lastrowid
            conn.commit()
        return f'/mock-pay/{txn_id}', txn_id, invoice_id

    @staticmethod
    def confirm_payment(txn_id):
        """确认支付结果（模拟自动成功）"""
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM billing_invoices WHERE payment_gateway_txn_id=?', (txn_id,))
            inv = c.fetchone()
            if not inv:
                return False, '订单不存在'
            c.execute('UPDATE billing_invoices SET status=?, paid_at=CURRENT_TIMESTAMP WHERE payment_gateway_txn_id=?',
                     ('paid', txn_id))
            conn.commit()
            return True, inv

    @staticmethod
    def process_refund(invoice_id, amount, reason=''):
        """处理退款（模拟）"""
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM billing_invoices WHERE id=? AND status=?', (invoice_id, 'paid'))
            inv = c.fetchone()
            if not inv:
                return False, '订单不存在或未支付'
            refund_amt = min(amount, inv['amount'])
            c.execute('''UPDATE billing_invoices SET status=?, refunded_at=CURRENT_TIMESTAMP,
                        refund_amount=?, refund_reason=? WHERE id=?''',
                     ('refunded', refund_amt, reason, invoice_id))
            conn.commit()
            return True, refund_amt


# ── 订阅管理 API ──