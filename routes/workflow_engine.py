"""
workflow_engine.py - 工作流执行引擎

工作流引擎是系统的"自动化大脑"，它负责：
1. 监听系统事件（扫码、创建工单、表单提交等）
2. 检查条件是否满足（如扫码次数是否超过阈值）
3. 按顺序执行预设的动作（如发送通知、创建工单、调用Webhook）

工作流由以下元素组成：
- 触发器（Trigger）：定义什么事件会启动工作流
- 条件（Condition）：检查事件数据是否满足条件
- 动作（Action）：条件满足后执行的操作
- 节点（Node）：工作流中的每个步骤
- 边（Edge）：节点之间的连线，定义执行顺序

示例场景：
当某个二维码被扫码超过100次时 → 自动发送通知给管理员 → 并创建统计工单
"""

import json
import sqlite3
import time as _time
from datetime import datetime
from routes.shared import get_db, logger, log_action


# ============ 工作流类型定义 ============

TRIGGER_TYPES = {
    'qrcode:scan': {'label': '二维码被扫码', 'event_fields': ['qrcode_id', 'qrcode_title', 'scan_count', 'scanned_at']},
    'qrcode:created': {'label': '二维码创建', 'event_fields': ['qrcode_id', 'qrcode_title', 'created_by', 'created_at']},
    'qrcode:expired': {'label': '二维码过期', 'event_fields': ['qrcode_id', 'qrcode_title', 'expired_at']},
    'qrcode:scan_threshold': {'label': '扫码次数达阈值', 'event_fields': ['qrcode_id', 'qrcode_title', 'scan_count', 'threshold']},
    'form:submitted': {'label': '表单提交', 'event_fields': ['form_id', 'form_name', 'submission_id', 'submitter_id', 'submitted_at']},
    'form:approved': {'label': '表单审批通过', 'event_fields': ['form_id', 'form_name', 'submission_id', 'approved_at']},
    'form:rejected': {'label': '表单审批拒绝', 'event_fields': ['form_id', 'form_name', 'submission_id', 'rejected_at']},
    'workorder:created': {'label': '工单创建', 'event_fields': ['workorder_id', 'workorder_title', 'priority', 'created_by', 'created_at']},
    'workorder:status_changed': {'label': '工单状态变更', 'event_fields': ['workorder_id', 'workorder_title', 'old_status', 'new_status', 'changed_at']},
    'workorder:overdue': {'label': '工单超时未处理', 'event_fields': ['workorder_id', 'workorder_title', 'created_at', 'overdue_hours']},
    'inspection:submitted': {'label': '巡检提交', 'event_fields': ['inspection_id', 'plan_id', 'inspector_id', 'result', 'submitted_at']},
    'inspection:abnormal': {'label': '巡检结果异常', 'event_fields': ['inspection_id', 'plan_id', 'inspector_id', 'result', 'note', 'submitted_at']},
    'schedule:time': {'label': '定时触发', 'event_fields': ['scheduled_at', 'cron_expression']},
    'webhook:received': {'label': 'Webhook接收', 'event_fields': ['webhook_url', 'method', 'payload', 'received_at']},
}

ACTION_TYPES = {
    'notification:send': {'label': '发送站内通知', 'params': ['user_ids', 'title', 'message']},
    'webhook:call': {'label': '调用Webhook', 'params': ['url', 'method', 'headers', 'body']},
    'workorder:create': {'label': '创建工单', 'params': ['title', 'description', 'priority', 'assignee_id']},
    'field:update': {'label': '更新字段值', 'params': ['target_type', 'target_id', 'field', 'value']},
    'qrcode:status_change': {'label': '修改二维码状态', 'params': ['qrcode_id', 'new_status']},
    'delay:wait': {'label': '延时等待', 'params': ['seconds']},
}

CONDITION_OPERATORS = {
    'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'eq': '==', 'neq': '!=',
    'contains': '包含', 'not_contains': '不包含', 'starts_with': '开头是',
    'is_empty': '为空', 'is_not_empty': '不为空',
}


class WorkflowEngine:

    @staticmethod
    def resolve_field(data, field_path):
        if not field_path or not data:
            return None
        current = data
        for part in field_path.split('.'):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                return None
        return current

    @staticmethod
    def evaluate_condition(condition, event_data):
        field = condition.get('field', '')
        operator = condition.get('operator', 'eq')
        value = condition.get('value', '')

        actual = WorkflowEngine.resolve_field(event_data, field)

        if operator == 'is_empty':
            return actual is None or actual == '' or actual == 0
        if operator == 'is_not_empty':
            return actual is not None and actual != '' and actual != 0
        if operator == 'contains':
            return str(value).lower() in str(actual or '').lower()
        if operator == 'not_contains':
            return str(value).lower() not in str(actual or '').lower()
        if operator == 'starts_with':
            return str(actual or '').startswith(str(value))

        try:
            actual_num = float(actual) if actual is not None else 0
            value_num = float(value)
            if operator == 'gt': return actual_num > value_num
            if operator == 'gte': return actual_num >= value_num
            if operator == 'lt': return actual_num < value_num
            if operator == 'lte': return actual_num <= value_num
            if operator == 'eq': return actual_num == value_num
            if operator == 'neq': return actual_num != value_num
        except (ValueError, TypeError):
            if operator == 'eq': return str(actual) == str(value)
            if operator == 'neq': return str(actual) != str(value)
        return False

    @staticmethod
    def evaluate_conditions(conditions_config, event_data):
        if not conditions_config:
            return True
        logic = conditions_config.get('logic', 'AND')
        conditions = conditions_config.get('conditions', [])
        if not conditions:
            return True

        results = [WorkflowEngine.evaluate_condition(c, event_data) for c in conditions]
        return all(results) if logic == 'AND' else any(results)

    @staticmethod
    def execute_action(action_config, event_data, org_id):
        action_type = action_config.get('type', '')
        params = action_config.get('params', {})
        resolved = {}

        for k, v in params.items():
            if isinstance(v, str) and v.startswith('{{') and v.endswith('}}'):
                field_path = v[2:-2].strip()
                resolved[k] = WorkflowEngine.resolve_field(event_data, field_path)
            else:
                resolved[k] = v

        if action_type == 'notification:send':
            user_ids = resolved.get('user_ids', '')
            title = resolved.get('title', '工作流通知')
            message = resolved.get('message', '')
            if isinstance(user_ids, str):
                user_ids = [uid.strip() for uid in user_ids.split(',') if uid.strip()]
            with get_db() as conn:
                c = conn.cursor()
                for uid in user_ids:
                    try:
                        c.execute(
                            'INSERT INTO notifications (org_id, user_id, title, message, type, is_read) VALUES (?,?,?,?,?,0)',
                            (org_id, int(uid), title, message, 'workflow')
                        )
                    except (ValueError, sqlite3.IntegrityError):
                        pass
                conn.commit()
            return {'success': True, 'notified_users': len(user_ids)}

        elif action_type == 'webhook:call':
            import urllib.request
            url = resolved.get('url', '')
            method = resolved.get('method', 'POST').upper()
            headers_str = resolved.get('headers', '{}')
            body = resolved.get('body', '{}')
            try:
                headers = json.loads(headers_str) if isinstance(headers_str, str) else headers_str
            except json.JSONDecodeError:
                headers = {'Content-Type': 'application/json'}
            try:
                body_bytes = json.dumps(body).encode('utf-8') if isinstance(body, (dict, list)) else str(body).encode('utf-8')
            except Exception:
                body_bytes = str(body).encode('utf-8')
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=WORKFLOW_WEBHOOK_TIMEOUT) as resp:
                    return {'success': True, 'status': resp.status, 'response': resp.read().decode('utf-8', errors='replace')[:500]}
            except Exception as e:
                return {'success': False, 'error': str(e)}

        elif action_type == 'workorder:create':
            title = resolved.get('title', '自动创建工单')
            description = resolved.get('description', '')
            priority = resolved.get('priority', 'normal')
            assignee_id = resolved.get('assignee_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute(
                    'INSERT INTO workorders (org_id, title, description, priority, status, assignee_id, created_by) VALUES (?,?,?,?,?,?,?)',
                    (org_id, title, description, priority, 'open', assignee_id, 0)
                )
                wo_id = c.lastrowid
                conn.commit()
            return {'success': True, 'workorder_id': wo_id}

        elif action_type == 'field:update':
            target_type = resolved.get('target_type', '')
            target_id = resolved.get('target_id', '')
            field = resolved.get('field', '')
            value = resolved.get('value', '')
            table_map = {'qrcode': 'qrcodes', 'workorder': 'workorders', 'form': 'forms'}
            table = table_map.get(target_type)
            if table and target_id and field:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute(f'UPDATE {table} SET {field}=?, updated_at=? WHERE id=? AND org_id=?',
                              (value, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), target_id, org_id))
                    conn.commit()
                return {'success': True, 'updated': target_type, 'id': target_id}
            return {'success': False, 'error': '无效的更新目标'}

        elif action_type == 'qrcode:status_change':
            qrcode_id = resolved.get('qrcode_id', '')
            new_status = resolved.get('new_status', 'normal')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('UPDATE qrcodes SET current_status=?, updated_at=? WHERE id=? AND org_id=?',
                          (new_status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), qrcode_id, org_id))
                conn.commit()
            return {'success': True, 'qrcode_id': qrcode_id, 'new_status': new_status}

        elif action_type == 'delay:wait':
            seconds = min(int(resolved.get('seconds', 1)), 300)
            _time.sleep(seconds)
            return {'success': True, 'waited': seconds}

        return {'success': False, 'error': f'未知动作类型: {action_type}'}

    @staticmethod
    def execute_node(instance_id, node, event_data, org_id, log_entry=None):
        node_type = node.get('type', '')
        node_id = node.get('id', '')
        node_label = node.get('label', '')
        max_retries = node.get('max_retries', 3)

        if log_entry:
            log_id = log_entry['id']
        else:
            with get_db() as conn:
                c = conn.cursor()
                c.execute(
                    'INSERT INTO workflow_execution_logs (instance_id, node_id, node_type, node_label, status, max_retries, started_at) '
                    'VALUES (?,?,?,?,?,?,?)',
                    (instance_id, node_id, node_type, node_label, 'running', max_retries,
                     datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )
                log_id = c.lastrowid
                conn.commit()

        for attempt in range(max_retries + 1):
            try:
                result = None
                if node_type == 'condition':
                    conditions = node.get('config', {}).get('conditions', {})
                    passed = WorkflowEngine.evaluate_conditions(conditions, event_data)
                    result = {'passed': passed, 'conditions': conditions}

                elif node_type == 'action':
                    action_config = node.get('config', {})
                    result = WorkflowEngine.execute_action(action_config, event_data, org_id)

                elif node_type == 'loop':
                    items_field = node.get('config', {}).get('items_field', '')
                    items = WorkflowEngine.resolve_field(event_data, items_field)
                    if not isinstance(items, list):
                        items = [items]
                    results = []
                    for item in items:
                        merged = {**event_data, 'loop_item': item}
                        results.append({'item': item})
                    result = {'loop_results': results, 'total': len(items)}

                elif node_type == 'parallel':
                    parallel_nodes = node.get('config', {}).get('nodes', [])
                    results = []
                    for pn in parallel_nodes:
                        pr = WorkflowEngine.execute_action(pn.get('config', {}), event_data, org_id)
                        results.append(pr)
                    result = {'parallel_results': results}

                with get_db() as conn:
                    c = conn.cursor()
                    c.execute(
                        'UPDATE workflow_execution_logs SET status=?, output_data=?, finished_at=? WHERE id=?',
                        ('success', json.dumps(result, ensure_ascii=False, default=str),
                         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), log_id)
                    )
                    conn.commit()
                return result

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"节点 {node_id} 执行失败，第{attempt+1}次重试: {e}")
                    _time.sleep(2 ** attempt)
                else:
                    with get_db() as conn:
                        c = conn.cursor()
                        c.execute(
                            'UPDATE workflow_execution_logs SET status=?, error_message=?, retry_count=?, finished_at=? WHERE id=?',
                            ('failed', str(e), attempt, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), log_id)
                        )
                        conn.commit()
                    raise

    @staticmethod
    def execute_workflow(workflow_id, org_id, trigger_event):
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM workflow_definitions WHERE id=? AND org_id=? AND is_enabled=1 AND is_deleted=0',
                      (workflow_id, org_id))
            wf = c.fetchone()
            if not wf:
                return {'success': False, 'error': '工作流不存在或未启用'}

            c.execute('SELECT * FROM workflow_versions WHERE workflow_id=? AND version=?',
                      (workflow_id, wf['current_version']))
            version = c.fetchone()
            if not version:
                return {'success': False, 'error': '工作流版本不存在'}

            nodes = json.loads(version['nodes_json'])
            edges = json.loads(version['edges_json'])

            c.execute(
                'INSERT INTO workflow_instances (org_id, workflow_id, workflow_version, trigger_event, status) VALUES (?,?,?,?,?)',
                (org_id, workflow_id, wf['current_version'], json.dumps(trigger_event, ensure_ascii=False, default=str), 'running')
            )
            instance_id = c.lastrowid
            conn.commit()

        adjacency = {}
        for edge in edges:
            src = edge.get('source', '')
            tgt = edge.get('target', '')
            if src not in adjacency:
                adjacency[src] = []
            adjacency[src].append(tgt)

        node_map = {n['id']: n for n in nodes}

        trigger_nodes = [n for n in nodes if n.get('type') == 'trigger']
        if not trigger_nodes:
            WorkflowEngine._fail_instance(instance_id, '工作流缺少触发器节点')
            return {'success': False, 'error': '工作流缺少触发器节点'}

        try:
            event_data = dict(trigger_event)
            visited = set()
            queue = [trigger_nodes[0]['id']]

            while queue:
                current_id = queue.pop(0)
                if current_id in visited:
                    continue
                visited.add(current_id)

                node = node_map.get(current_id)
                if not node:
                    continue

                with get_db() as conn:
                    conn.cursor().execute(
                        'UPDATE workflow_instances SET current_node_id=? WHERE id=?',
                        (current_id, instance_id)
                    )
                    conn.commit()

                result = WorkflowEngine.execute_node(instance_id, node, event_data, org_id)

                if result:
                    event_data = {**event_data, **{f'_{current_id}': result}}

                if node.get('type') == 'condition':
                    passed = result.get('passed', False) if result else False
                    next_nodes = adjacency.get(current_id, [])
                    if next_nodes:
                        target_id = None
                        for edge in edges:
                            if edge.get('source') == current_id:
                                edge_label = edge.get('label', '')
                                if passed and edge_label in ('true', 'yes', 'pass', ''):
                                    target_id = edge.get('target')
                                    break
                                if not passed and edge_label in ('false', 'no', 'fail'):
                                    target_id = edge.get('target')
                                    break
                        if not target_id:
                            target_id = next_nodes[0] if not passed else (next_nodes[1] if len(next_nodes) > 1 else next_nodes[0])
                        if target_id and target_id not in visited:
                            queue.append(target_id)
                else:
                    for next_id in adjacency.get(current_id, []):
                        if next_id not in visited:
                            queue.append(next_id)

            with get_db() as conn:
                conn.cursor().execute(
                    'UPDATE workflow_instances SET status=?, finished_at=? WHERE id=?',
                    ('completed', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), instance_id)
                )
                conn.commit()

            log_action('workflow_executed', 'workflow', workflow_id,
                       detail={'instance_id': instance_id, 'trigger': trigger_event.get('type', '')})
            return {'success': True, 'instance_id': instance_id}

        except Exception as e:
            WorkflowEngine._fail_instance(instance_id, str(e))
            return {'success': False, 'error': str(e), 'instance_id': instance_id}

    @staticmethod
    def _fail_instance(instance_id, error_msg):
        try:
            with get_db() as conn:
                conn.cursor().execute(
                    'UPDATE workflow_instances SET status=?, error_message=?, finished_at=? WHERE id=?',
                    ('failed', error_msg, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), instance_id)
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"标记工作流实例失败: {e}")

    @staticmethod
    def trigger_event(org_id, trigger_type, event_data):
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id FROM workflow_definitions WHERE org_id=? AND trigger_type=? AND is_enabled=1 AND is_deleted=0',
                (org_id, trigger_type)
            )
            wfs = c.fetchall()
        results = []
        for wf in wfs:
            event_data['type'] = trigger_type
            result = WorkflowEngine.execute_workflow(wf['id'], org_id, event_data)
            results.append(result)
        return results


# ============ 工作流触发器钩子 ============


def workflow_trigger_after_form_submit(form_id, org_id, submission_id, submitter_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT name FROM forms WHERE id=?', (form_id,))
        f = c.fetchone()
    event = {
        'form_id': form_id,
        'form_name': f['name'] if f else '',
        'submission_id': submission_id,
        'submitter_id': submitter_id,
        'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    WorkflowEngine.trigger_event(org_id, 'form:submitted', event)


def workflow_trigger_after_workorder_create(workorder_id, org_id, title, priority, created_by):
    event = {
        'workorder_id': workorder_id,
        'workorder_title': title or '',
        'priority': priority or 'normal',
        'created_by': created_by,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    WorkflowEngine.trigger_event(org_id, 'workorder:created', event)


def workflow_trigger_schedule_poll():
    """定时轮询触发器：处理 schedule:time 和 workorder:overdue"""
    results = []
    now = datetime.now()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, org_id, trigger_config FROM workflow_definitions WHERE trigger_type=? AND is_enabled=1 AND is_deleted=0',
                  ('schedule:time',))
        for wf in c.fetchall():
            try:
                cfg = json.loads(wf['trigger_config'] or '{}')
                cron_expr = cfg.get('cron_expression', '')
                last_run = cfg.get('last_run')
                if last_run:
                    last_dt = datetime.strptime(last_run, '%Y-%m-%d %H:%M:%S')
                    if (now - last_dt).total_seconds() < 60:
                        continue
                event = {
                    'scheduled_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'cron_expression': cron_expr
                }
                result = WorkflowEngine.execute_workflow(wf['id'], wf['org_id'], event)
                results.append(result)
                cfg['last_run'] = now.strftime('%Y-%m-%d %H:%M:%S')
                c.execute('UPDATE workflow_definitions SET trigger_config=? WHERE id=?',
                         (json.dumps(cfg, ensure_ascii=False), wf['id']))
            except Exception as e:
                logger.error(f"定时触发器执行失败 workflow_id={wf['id']}: {e}")

        c.execute('SELECT id, org_id, trigger_config FROM workflow_definitions WHERE trigger_type=? AND is_enabled=1 AND is_deleted=0',
                  ('workorder:overdue',))
        for wf in c.fetchall():
            try:
                cfg = json.loads(wf['trigger_config'] or '{}')
                overdue_hours = int(cfg.get('overdue_hours', DEFAULT_OVERDUE_HOURS))
                last_check = cfg.get('last_check')
                if last_check:
                    last_dt = datetime.strptime(last_check, '%Y-%m-%d %H:%M:%S')
                    if (now - last_dt).total_seconds() < SCHEDULE_POLL_INTERVAL:
                        continue
                c2 = conn.cursor()
                c2.execute('''SELECT id, title, created_at FROM workorders
                            WHERE org_id=? AND status='open'
                            AND (julianday(CURRENT_TIMESTAMP) - julianday(created_at)) * 24 > ?''',
                         (wf['org_id'], overdue_hours))
                for wo in c2.fetchall():
                    event = {
                        'workorder_id': wo['id'],
                        'workorder_title': wo['title'] or '',
                        'created_at': wo['created_at'] if 'created_at' in wo.keys() else '',
                        'overdue_hours': overdue_hours
                    }
                    result = WorkflowEngine.execute_workflow(wf['id'], wf['org_id'], event)
                    results.append(result)
                cfg['last_check'] = now.strftime('%Y-%m-%d %H:%M:%S')
                c.execute('UPDATE workflow_definitions SET trigger_config=? WHERE id=?',
                         (json.dumps(cfg, ensure_ascii=False), wf['id']))
            except Exception as e:
                logger.error(f"超时触发器执行失败 workflow_id={wf['id']}: {e}")
        conn.commit()
    return results