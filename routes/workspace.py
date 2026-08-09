"""
workspace.py - 工作台仪表盘模块
提供系统的首页仪表盘和统一搜索功能。

工作台是用户登录后看到的第一屏，汇总展示所有业务数据的状态。
包括：统计数据、待办事项、今日动态、趋势图表等。

主要功能：
1. 仪表盘统计：二维码数量、扫码次数、表单提交数等
2. 工作台汇总：问候语、待办事项、今日统计、趋势图
3. 标签管理：创建和管理标签，给二维码打标签
4. 统一搜索：跨模块搜索二维码、资产、工单等

数据展示：
- 待办事项：逾期巡检、待处理工单、待审批表单、异常二维码
- 今日统计：扫码数、新增二维码、新增表单、新增工单
- 7日趋势：最近7天的扫码趋势折线图
- 最近活动：系统最近的操作日志
- 资源概览：二维码、资产、表单、文件的总数
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, logger, ROLES,
    parse_pagination, SEARCHABLE_RESOURCES
)

workspace_bp = Blueprint('workspace', __name__)


@workspace_bp.route('/api/dashboard/stats', methods=['GET'])
@login_required
def get_dashboard_stats_enhanced():
    """获取仪表盘统计（增强版）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            
            c.execute('SELECT COUNT(*) FROM qrcodes WHERE org_id = ? AND is_active = 1 AND is_deleted = 0', (org_id,))
            qrcode_count = c.fetchone()[0]
            
            c.execute('SELECT SUM(scan_count) FROM qrcodes WHERE org_id = ? AND is_active = 1 AND is_deleted = 0', (org_id,))
            total_scans = c.fetchone()[0] or 0
            
            c.execute('''SELECT COUNT(*) FROM form_submissions fs 
                        JOIN qrcodes q ON fs.qrcode_id = q.id WHERE q.org_id = ? AND q.is_deleted = 0''', (org_id,))
            submission_count = c.fetchone()[0]
            
            today = datetime.now().strftime('%Y-%m-%d')
            c.execute('''SELECT COUNT(*) FROM scan_logs sl
                        JOIN qrcodes q ON sl.qrcode_id = q.id
                        WHERE q.org_id=? AND q.is_deleted = 0 AND date(sl.scan_time)=?''', (org_id, today))
            today_scans = c.fetchone()[0]
            
            c.execute('''SELECT COUNT(*) FROM scan_logs sl
                        JOIN qrcodes q ON sl.qrcode_id = q.id
                        WHERE q.org_id=? AND q.is_deleted = 0 AND sl.scan_time >= datetime('now','-7 days')''', (org_id,))
            week_scans = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM qrcodes WHERE org_id=? AND is_active=1 AND archive_status=0 AND is_deleted=0', (org_id,))
            active_qrcodes = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM dynamic_links WHERE org_id=? AND status='active'", (org_id,))
            total_dynamic_links = c.fetchone()[0]
        
        return jsonify({
            'success': True,
            'stats': {
                'qrcode_count': qrcode_count,
                'total_scans': total_scans,
                'submission_count': submission_count,
                'today_scans': today_scans,
                'week_scans': week_scans,
                'active_qrcodes': active_qrcodes,
                'total_dynamic_links': total_dynamic_links
            }
        })
    
    except Exception as e:
        logger.error(f"仪表盘统计失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


# ============ 标签系统 API ============


@workspace_bp.route('/api/workspace/summary', methods=['GET'])
@require_permission('qrcode:view')
def workspace_summary():
    """工作台汇总数据"""
    try:
        org_id = session.get('org_id')
        username = session.get('username', '')
        role_type = session.get('role', 'viewer')
        role_label = ROLES.get(role_type, {}).get('label', '')

        current_hour = datetime.now().hour
        if 6 <= current_hour <= 11:
            greeting_word = '早上好'
        elif 12 <= current_hour <= 13:
            greeting_word = '中午好'
        elif 14 <= current_hour <= 17:
            greeting_word = '下午好'
        elif 18 <= current_hour <= 22:
            greeting_word = '晚上好'
        else:
            greeting_word = '你好'

        pending = {
            'overdue_inspections': {'count': 0, 'list': []},
            'open_workorders': {'count': 0, 'list': []},
            'pending_submissions': {'count': 0, 'list': []},
            'abnormal_qrcodes': {'count': 0, 'list': []},
            'total_pending': 0
        }

        today = datetime.now().date()

        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM inspection_plans ip
                        WHERE ip.org_id = ? AND ip.is_active = 1
                          AND (
                            ip.last_completed IS NULL
                        OR datetime(ip.last_completed, '+' || ip.frequency_days || ' days') < datetime('now')
                          )''', (org_id,))
            pending['overdue_inspections']['count'] = c.fetchone()[0]
            c.execute('''SELECT ip.*, a.name as asset_name
                        FROM inspection_plans ip
                        LEFT JOIN assets a ON ip.asset_id = a.id
                        WHERE ip.org_id = ? AND ip.is_active = 1
                          AND (
                            ip.last_completed IS NULL
                            OR datetime(ip.last_completed, '+' || ip.frequency_days || ' days') < datetime('now')
                          )
                        ORDER BY ip.created_at DESC LIMIT 5''', (org_id,))
            rows = c.fetchall()
            for r in rows:
                days_overdue = 0
                if r['last_completed']:
                    try:
                        last_date = datetime.strptime(r['last_completed'][:10], '%Y-%m-%d').date()
                        due_date = last_date + timedelta(days=r['frequency_days'])
                        days_overdue = (today - due_date).days
                    except:
                        pass
                pending['overdue_inspections']['list'].append({
                    'plan_id': r['id'], 'asset_name': r['asset_name'],
                    'frequency_days': r['frequency_days'], 'last_completed': r['last_completed'],
                    'days_overdue': days_overdue
                })

            c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM workorders w
                        WHERE w.org_id = ? AND w.status IN ('open','processing')''', (org_id,))
            pending['open_workorders']['count'] = c.fetchone()[0]
            c.execute('''SELECT w.*, a.name as asset_name, u.username as assignee_name
                        FROM workorders w
                        LEFT JOIN assets a ON w.asset_id = a.id
                        LEFT JOIN users u ON w.assignee_id = u.id
                        WHERE w.org_id = ? AND w.status IN ('open','processing')
                        ORDER BY
                            CASE w.priority
                                WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                                WHEN 'normal' THEN 3 ELSE 4
                            END,
                            w.created_at DESC
                        LIMIT 5''', (org_id,))
            rows = c.fetchall()
            for r in rows:
                pending['open_workorders']['list'].append({
                    'workorder_id': r['id'], 'title': r['title'],
                    'priority': r['priority'], 'status': r['status'],
                    'asset_name': r['asset_name'], 'assignee_name': r['assignee_name'],
                    'created_at': r['created_at']
                })

            c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM form_submissions fs
                        JOIN forms f ON fs.form_id = f.id
                        JOIN qrcodes q ON fs.qrcode_id = q.id
                        WHERE q.org_id = ? AND fs.approval_state = 'pending'
                        ''', (org_id,))
            pending['pending_submissions']['count'] = c.fetchone()[0]
            c.execute('''SELECT fs.id as submission_id, f.form_name, q.title as qrcode_title, fs.created_at
                        FROM form_submissions fs
                        JOIN forms f ON fs.form_id = f.id
                        JOIN qrcodes q ON fs.qrcode_id = q.id
                        WHERE q.org_id = ? AND fs.approval_state = 'pending'
                        ORDER BY fs.created_at DESC LIMIT 5''', (org_id,))
            rows = c.fetchall()
            for r in rows:
                pending['pending_submissions']['list'].append({
                    'submission_id': r['submission_id'],
                    'form_name': r['form_name'],
                    'qrcode_title': r['qrcode_title'],
                    'created_at': r['created_at']
                })

            c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM qrcodes q
                        LEFT JOIN dynamic_links dl ON q.id = dl.qrcode_id
                        WHERE q.org_id = ? AND q.is_active = 1
                          AND (
                            dl.status IN ('expired', 'exhausted', 'disabled')
                            OR (dl.max_scans > 0 AND dl.scan_count >= dl.max_scans * 0.9)
                          )''', (org_id,))
            pending['abnormal_qrcodes']['count'] = c.fetchone()[0]
            c.execute('''SELECT q.id as qrcode_id, q.title, dl.status as link_status,
                               dl.scan_count, dl.max_scans
                        FROM qrcodes q
                        LEFT JOIN dynamic_links dl ON q.id = dl.qrcode_id
                        WHERE q.org_id = ? AND q.is_active = 1
                          AND (
                            dl.status IN ('expired', 'exhausted', 'disabled')
                            OR (dl.max_scans > 0 AND dl.scan_count >= dl.max_scans * 0.9)
                          )
                        LIMIT 5''', (org_id,))
            rows = c.fetchall()
            for r in rows:
                pending['abnormal_qrcodes']['list'].append({
                    'qrcode_id': r['qrcode_id'],
                    'title': r['title'],
                    'link_status': r['link_status'],
                    'scan_count': r['scan_count'],
                    'max_scans': r['max_scans']
                })

            pending['total_pending'] = (
                pending['overdue_inspections']['count'] + pending['open_workorders']['count'] +
                pending['pending_submissions']['count'] + pending['abnormal_qrcodes']['count']
            )

            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_stats = {'scans': 0, 'new_qrcodes': 0, 'new_forms': 0, 'new_workorders': 0}

            c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM scan_logs sl
                        JOIN qrcodes q ON sl.qrcode_id = q.id
                        WHERE q.org_id = ? AND sl.scan_time >= ?''', (org_id, today_start))
            today_stats['scans'] = c.fetchone()[0]
            c.execute('''SELECT COUNT(*) FROM qrcodes
                        WHERE org_id = ? AND is_active = 1 AND created_at >= ?''', (org_id, today_start))
            today_stats['new_qrcodes'] = c.fetchone()[0]
            c.execute('''SELECT COUNT(*) FROM form_submissions fs
                        JOIN qrcodes q ON fs.qrcode_id = q.id
                        WHERE q.org_id = ? AND fs.created_at >= ?''', (org_id, today_start))
            today_stats['new_forms'] = c.fetchone()[0]
            c.execute('''SELECT COUNT(*) FROM workorders
                        WHERE org_id = ? AND created_at >= ?''', (org_id, today_start))
            today_stats['new_workorders'] = c.fetchone()[0]

            end_date = today
            start_date = end_date - timedelta(days=6)
            date_counts = {}
            current = start_date
            while current <= end_date:
                date_counts[current.strftime('%Y-%m-%d')] = 0
                current += timedelta(days=1)

            c = conn.cursor()
            c.execute('''SELECT date(sl.scan_time) as day, COUNT(*) as count
                        FROM scan_logs sl
                        JOIN qrcodes q ON sl.qrcode_id = q.id
                        WHERE q.org_id = ? AND sl.scan_time >= datetime('now', '-7 days')
                        GROUP BY date(sl.scan_time)
                        ORDER BY day ASC''', (org_id,))
            for r in c.fetchall():
                if r['day'] in date_counts:
                    date_counts[r['day']] = r['count']

            week_trend = [{'date': day, 'count': date_counts[day]} for day in sorted(date_counts)]

            recent_activities = []
            c = conn.cursor()
            c.execute('''SELECT al.*, u.username
                        FROM audit_logs al
                        LEFT JOIN users u ON al.user_id = u.id
                        WHERE al.org_id = ?
                        ORDER BY al.created_at DESC LIMIT 10''', (org_id,))
            for r in c.fetchall():
                recent_activities.append({
                    'action': r['action'], 'target_type': r['target_type'],
                    'target_id': r['target_id'], 'username': r['username'],
                    'created_at': r['created_at'], 'detail': r['detail']
                })

            resource_overview = {
                'total_qrcodes': 0, 'total_assets': 0, 'total_forms': 0,
                'total_files': 0, 'storage_used': 0
            }
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM qrcodes WHERE org_id = ? AND is_active = 1 AND is_deleted = 0', (org_id,))
            resource_overview['total_qrcodes'] = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM assets WHERE org_id = ?', (org_id,))
            resource_overview['total_assets'] = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM forms WHERE org_id = ?', (org_id,))
            resource_overview['total_forms'] = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM files WHERE org_id = ?', (org_id,))
            resource_overview['total_files'] = c.fetchone()[0]
            c.execute('SELECT COALESCE(SUM(size), 0) FROM files WHERE org_id = ?', (org_id,))
            resource_overview['storage_used'] = c.fetchone()[0]

            return jsonify({
                'success': True,
                'greeting': {
                    'text': f"{greeting_word}，{username}",
                    'role_label': role_label,
                    'time': datetime.now().strftime('%Y年%m月%d日 %H:%M')
                },
                'pending': pending,
                'today_stats': today_stats,
                'week_trend': week_trend,
                'recent_activities': recent_activities,
                'resource_overview': resource_overview
            })
    except Exception as e:
        logger.error(f"工作台数据查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


def _parse_search_tokens(q, operator):
    if not q:
        return [], operator
    tokens = [t.strip() for t in q.split() if t.strip()]
    return tokens, operator


def _build_search_query(res, rt, tokens, parsed_op, org_id, filters):
    table = res['table']
    title_field = res['title_field']

    creator_col_map = {
        'qrcode': 'COALESCE(creator_id, 0)',
        'form': '0',
        'workorder': 'COALESCE(created_by, 0)',
        'asset': 'COALESCE(created_by, 0)',
        'file': 'COALESCE(created_by, 0)',
    }
    status_col_map = {
        'qrcode': "COALESCE(status, '')",
        'form': "COALESCE(status, 'active')",
        'workorder': "COALESCE(status, 'open')",
        'asset': "COALESCE(status, 'normal')",
        'file': "''",
    }
    has_is_deleted = {'qrcode', 'form', 'workorder', 'file'}

    creator_col = creator_col_map.get(rt, '0')
    status_col = status_col_map.get(rt, "''")

    params = []
    conditions = [f'{table}.org_id = ?']
    params.append(org_id)

    if rt in has_is_deleted:
        conditions.append(f'{table}.is_deleted = 0')

    if tokens:
        if parsed_op == 'AND':
            for token in tokens:
                conditions.append(f'{table}.{title_field} LIKE ?')
                params.append(f'%{token}%')
        elif parsed_op == 'OR':
            or_parts = []
            for token in tokens:
                or_parts.append(f'{table}.{title_field} LIKE ?')
                params.append(f'%{token}%')
            conditions.append(f'({" OR ".join(or_parts)})')
        elif parsed_op == 'NOT':
            for token in tokens:
                conditions.append(f'{table}.{title_field} NOT LIKE ?')
                params.append(f'%{token}%')

    if filters.get('status'):
        if rt != 'file':
            conditions.append(f'{table}.status = ?')
            params.append(filters['status'])
    if filters.get('creator'):
        conditions.append(f'{creator_col} = ?')
        params.append(int(filters['creator']))
    if filters.get('tags') and rt == 'qrcode':
        conditions.append(f'{table}.tags LIKE ?')
        params.append(f'%{filters["tags"]}%')
    if filters.get('date_from'):
        conditions.append(f'{table}.created_at >= ?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        conditions.append(f'{table}.created_at <= ?')
        params.append(filters['date_to'])

    where_clause = ' AND '.join(conditions)
    sql = (
        f"SELECT {table}.id, {table}.{title_field} AS title, "
        f"'{rt}' AS resource_type_key, "
        f"{status_col} AS status_val, "
        f"{creator_col} AS creator_id, "
        f"{table}.created_at "
        f"FROM {table} WHERE {where_clause}"
    )

    return sql, params


@workspace_bp.route('/api/search', methods=['GET'])
@login_required
def api_unified_search():
    """统一搜索（支持多资源类型、关键词、高级条件）"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        q = (request.args.get('q') or '').strip()
        resource_type = (request.args.get('type') or '').strip()
        operator = (request.args.get('operator') or 'AND').strip().upper()
        status = (request.args.get('status') or '').strip()
        creator = (request.args.get('creator') or '').strip()
        tags = (request.args.get('tags') or '').strip()
        date_from = (request.args.get('date_from') or '').strip()
        date_to = (request.args.get('date_to') or '').strip()
        page, size, offset = parse_pagination(max_size=50)

        if operator not in ('AND', 'OR', 'NOT'):
            operator = 'AND'

        filters = {k: v for k, v in [('status', status), ('creator', creator),
                    ('tags', tags), ('date_from', date_from), ('date_to', date_to)] if v}

        record_history = bool(q) and page == 1

        with get_db() as conn:
            c = conn.cursor()

            if record_history:
                try:
                    c.execute('''INSERT INTO search_history (org_id, user_id, keyword, resource_type)
                                VALUES (?,?,?,?)''', (org_id, user_id, q, resource_type or None))
                except Exception:
                    pass

            resource_types = [resource_type] if resource_type and resource_type in SEARCHABLE_RESOURCES else list(SEARCHABLE_RESOURCES)

            tokens, parsed_op = _parse_search_tokens(q, operator)

            queries = []
            all_params = []
            for rt in resource_types:
                res = SEARCHABLE_RESOURCES[rt]
                if not q and not filters:
                    continue
                sql, params = _build_search_query(res, rt, tokens, parsed_op, org_id, filters)
                queries.append(sql)
                all_params.extend(params)

            if not queries:
                return jsonify({'success': True, 'total': 0, 'page': page, 'size': size,
                              'total_pages': 0, 'results': []})

            union_sql = ' UNION ALL '.join(queries)
            count_sql = f'SELECT COUNT(*) FROM ({union_sql})'
            total = c.execute(count_sql, all_params).fetchone()[0]

            paged_sql = f'SELECT * FROM ({union_sql}) ORDER BY created_at DESC LIMIT ? OFFSET ?'
            rows = c.execute(paged_sql, all_params + [size, offset]).fetchall()

        results = []
        for r in rows:
            rt = r['resource_type_key']
            res_info = SEARCHABLE_RESOURCES.get(rt, {})
            rt_label = res_info.get('label', rt)
            rt_icon = res_info.get('icon', '📄')
            rt_color = res_info.get('color', '#6366F1')

            status_val = r['status_val']
            status_map = res_info.get('statuses', {})
            status_label = status_map.get(str(status_val), str(status_val)) if status_val is not None else ''

            result = {
                'id': r['id'], 'title': r['title'] or '', 'resource_type': rt,
                'resource_type_label': rt_label, 'resource_type_icon': rt_icon,
                'resource_type_color': rt_color, 'status': status_val,
                'status_label': status_label, 'creator_id': r['creator_id'],
                'created_at': r['created_at']
            }
            results.append(result)

        return jsonify({'success': True, 'total': total, 'page': page, 'size': size,
                       'total_pages': max(1, (total + size - 1) // size), 'results': results})
    except Exception as e:
        logger.error(f"搜索失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.searchFailed', '搜索失败')}), 500



@workspace_bp.route('/api/search/suggestions', methods=['GET'])
@login_required
def api_search_suggestions():
    """搜索建议（基于历史搜索 + 热门关键词）"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        q = (request.args.get('q') or '').strip()

        with get_db() as conn:
            c = conn.cursor()

            suggestions = []

            if q:
                c.execute('''SELECT DISTINCT keyword FROM search_history
                            WHERE org_id=? AND user_id=? AND keyword LIKE ?
                            ORDER BY created_at DESC LIMIT 5''',
                         (org_id, user_id, f'{q}%'))
                for row in c.fetchall():
                    suggestions.append({'keyword': row['keyword'], 'source': 'history'})

            if len(suggestions) < 5:
                c.execute('''SELECT DISTINCT keyword, COUNT(*) as cnt FROM search_history
                            WHERE org_id=? AND keyword LIKE ?
                            GROUP BY keyword ORDER BY cnt DESC LIMIT ?''',
                         (org_id, f'%{q}%' if q else '%', 5 - len(suggestions)))
                for row in c.fetchall():
                    kw = row['keyword']
                    if not any(s['keyword'] == kw for s in suggestions):
                        suggestions.append({'keyword': kw, 'source': 'popular'})

        return jsonify({'success': True, 'suggestions': suggestions[:8]})
    except Exception as e:
        logger.error(f"搜索建议失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workspace_bp.route('/api/search/history', methods=['GET'])
@login_required
def api_search_history():
    """最近搜索历史"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT keyword, resource_type, MAX(created_at) as created_at
                        FROM search_history WHERE org_id=? AND user_id=?
                        GROUP BY keyword, resource_type
                        ORDER BY created_at DESC LIMIT 20''', (org_id, user_id))
            rows = c.fetchall()

        history = [{
            'keyword': r['keyword'], 'resource_type': r['resource_type'],
            'created_at': r['created_at']
        } for r in rows]

        return jsonify({'success': True, 'history': history})
    except Exception as e:
        logger.error(f"搜索历史查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workspace_bp.route('/api/search/history', methods=['DELETE'])
@login_required
def api_search_history_clear():
    """清除搜索历史"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM search_history WHERE org_id=? AND user_id=?', (org_id, user_id))
            conn.commit()

        return jsonify({'success': True, 'message': '搜索历史已清除'})
    except Exception as e:
        logger.error(f"清除搜索历史失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.clearFailed', '清除失败')}), 500



@workspace_bp.route('/api/search/saved', methods=['GET'])
@login_required
def api_search_saved_list():
    """已保存的搜索列表"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT * FROM saved_searches
                        WHERE org_id=? AND user_id=? ORDER BY created_at DESC''', (org_id, user_id))
            rows = c.fetchall()

        saved = [{
            'id': r['id'], 'name': r['name'],
            'query': json.loads(r['query_json']), 'created_at': r['created_at']
        } for r in rows]

        return jsonify({'success': True, 'saved': saved})
    except Exception as e:
        logger.error(f"已保存搜索查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@workspace_bp.route('/api/search/saved', methods=['POST'])
@login_required
def api_search_saved_create():
    """保存搜索"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        name = (data.get('name') or '').strip()
        query = data.get('query', {})

        if not name:
            return jsonify({'error': _t('error.searchNameRequired', '搜索名称不能为空')}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO saved_searches (org_id, user_id, name, query_json)
                        VALUES (?,?,?,?)''', (org_id, user_id, name, json.dumps(query)))
            conn.commit()
            search_id = c.lastrowid

        return jsonify({'success': True, 'id': search_id, 'message': '搜索已保存'})
    except Exception as e:
        logger.error(f"保存搜索失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.saveFailed', '保存失败')}), 500



@workspace_bp.route('/api/search/saved/<int:search_id>', methods=['DELETE'])
@login_required
def api_search_saved_delete(search_id):
    """删除已保存的搜索"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM saved_searches WHERE id=? AND org_id=? AND user_id=?',
                     (search_id, org_id, user_id))
            conn.commit()

        return jsonify({'success': True, 'message': '搜索已删除'})
    except Exception as e:
        logger.error(f"删除已保存搜索失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500


# ============ 批量操作中心 ============

BATCH_RESOURCE_TABLES = {
    'qrcode': 'qrcodes',
    'file': 'files',
    'form': 'forms',
    'workorder': 'workorders',
    'inspection': 'inspection_records',
}

BATCH_ACTIONS = {
    'delete': {'label': '删除', 'icon': '🗑', 'color': '#EF4444', 'reversible': True},
    'modify': {'label': '修改', 'icon': '✏', 'color': '#F59E0B', 'reversible': True},
    'toggle': {'label': '启停', 'icon': '🔘', 'color': '#22C55E', 'reversible': True},
    'export': {'label': '导出', 'icon': '📥', 'color': '#6366F1', 'reversible': False},
    'tag': {'label': '标签', 'icon': '🏷', 'color': '#8B5CF6', 'reversible': True},
    'permission': {'label': '权限', 'icon': '🔒', 'color': '#EC4899', 'reversible': True},
    'archive': {'label': '归档', 'icon': '📁', 'color': '#6B7280', 'reversible': True},
}

BATCH_EXECUTORS = {}
ACTIVE_BATCH_TASKS = {}


def _batch_audit(org_id, user_id, task_id, action, resource_type, resource_id, detail=''):
    """记录批量操作审计日志"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO batch_audit_log (org_id, user_id, task_id, action, resource_type, resource_id, detail)
                        VALUES (?,?,?,?,?,?,?)''',
                     (org_id, user_id, task_id, action, resource_type, resource_id, detail))
            conn.commit()
    except Exception:
        pass


def _snapshot_resource(resource_type, resource_id):
    """获取资源快照（用于回滚）"""
    table = BATCH_RESOURCE_TABLES.get(resource_type)
    if not table:
        return None
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(f'SELECT * FROM {table} WHERE id=?', (resource_id,))
            row = c.fetchone()
            if row:
                return {k: row[k] for k in row.keys()}
    except Exception:
        pass
    return None


def _execute_batch_task(task_id):
    """异步执行批量任务"""
    task_info = None
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM batch_tasks WHERE id=?', (task_id,))
            row = c.fetchone()
            if not row or row['status'] == 'cancelled':
                return
            task_info = dict(row)
            c.execute('UPDATE batch_tasks SET status=?, started_at=? WHERE id=?',
                     ('running', datetime.now(), task_id))
            conn.commit()

        resource_type = task_info['resource_type']
        task_type = task_info['task_type']
        params = json.loads(task_info['params_json'] or '{}')
        resource_ids = params.get('resource_ids', [])

        if not resource_ids:
            with get_db() as conn:
                c = conn.cursor()
                c.execute('UPDATE batch_tasks SET status=?, error_msg=?, completed_at=? WHERE id=?',
                         ('failed', '没有选中任何资源', datetime.now(), task_id))
                conn.commit()
            return

        total = len(resource_ids)
        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE batch_tasks SET total_count=? WHERE id=?', (total, task_id))
            conn.commit()

        for i, rid in enumerate(resource_ids):
            if task_id in ACTIVE_BATCH_TASKS and ACTIVE_BATCH_TASKS[task_id].get('cancelled'):
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute('UPDATE batch_tasks SET status=? WHERE id=?', ('cancelled', task_id))
                    conn.commit()
                return

            snapshot = _snapshot_resource(resource_type, rid) if BATCH_ACTIONS.get(task_type, {}).get('reversible') else None
            item_status = 'success'
            error_msg = ''

            try:
                _apply_batch_action(resource_type, task_type, rid, params)
            except Exception as e:
                error_msg = str(e)
                item_status = 'failed'
                if params.get('retry_count', 0) < params.get('max_retries', 3):
                    for attempt in range(params.get('max_retries', 3)):
                        try:
                            _apply_batch_action(resource_type, task_type, rid, params)
                            item_status = 'success'
                            error_msg = ''
                            break
                        except Exception as re:
                            error_msg = str(re)

            resource_title = snapshot.get('title') or snapshot.get('name') or snapshot.get('form_name') or str(rid) if snapshot else str(rid)

            with get_db() as conn:
                c = conn.cursor()
                c.execute('''INSERT INTO batch_task_items (task_id, resource_id, resource_type, title, action, status, error_msg, snapshot_json, processed_at)
                            VALUES (?,?,?,?,?,?,?,?,?)''',
                         (task_id, rid, resource_type, resource_title, task_type, item_status,
                          error_msg, json.dumps(snapshot) if snapshot else None, datetime.now()))
                conn.commit()

            _batch_audit(task_info['org_id'], task_info['user_id'], task_id, task_type, resource_type, rid,
                        f'批量{task_type}: {resource_title} - {item_status}')

            success_inc = 1 if item_status == 'success' else 0
            fail_inc = 1 if item_status == 'failed' else 0
            with get_db() as conn:
                c = conn.cursor()
                c.execute('''UPDATE batch_tasks SET success_count=success_count+?, fail_count=fail_count+?
                            WHERE id=?''', (success_inc, fail_inc, task_id))
                conn.commit()

        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE batch_tasks SET status=?, completed_at=? WHERE id=?',
                     ('completed', datetime.now(), task_id))
            conn.commit()

    except Exception as e:
        logger.error(f"批量任务执行失败: {e}", exc_info=True)
        if task_id:
            with get_db() as conn:
                c = conn.cursor()
                c.execute('UPDATE batch_tasks SET status=?, error_msg=?, completed_at=? WHERE id=?',
                         ('failed', str(e), datetime.now(), task_id))
                conn.commit()


def _apply_batch_action(resource_type, task_type, resource_id, params):
    """执行单个批量操作"""
    table = BATCH_RESOURCE_TABLES.get(resource_type)
    if not table:
        raise ValueError(f'未知资源类型: {resource_type}')

    with get_db() as conn:
        c = conn.cursor()

        if task_type == 'delete':
            c.execute(f'UPDATE {table} SET is_active=0 WHERE id=?', (resource_id,))
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'modify':
            updates = params.get('updates', {})
            if not updates:
                raise ValueError('没有修改内容')
            set_clause = ', '.join([f'{k}=?' for k in updates])
            values = list(updates.values()) + [resource_id]
            c.execute(f'UPDATE {table} SET {set_clause} WHERE id=?', values)
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'toggle':
            new_state = params.get('target_state', 1)
            c.execute(f'UPDATE {table} SET is_active=? WHERE id=?', (new_state, resource_id))
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'tag':
            tag_value = params.get('tag', '')
            c.execute(f'UPDATE {table} SET tags=? WHERE id=?', (tag_value, resource_id))
            if c.rowcount == 0:
                raise ValueError(f'资源不存在: {resource_id}')

        elif task_type == 'permission':
            new_permission = params.get('permission', '')
            if table == 'files':
                c.execute(f'UPDATE {table} SET description=? WHERE id=?', (f'[权限:{new_permission}]', resource_id))
            else:
                raise ValueError('该资源类型不支持权限操作')

        elif task_type == 'archive':
            if table == 'qrcodes':
                c.execute(f'UPDATE {table} SET current_status=? WHERE id=?', ('archived', resource_id))
            elif table == 'workorders':
                c.execute(f'UPDATE {table} SET status=? WHERE id=?', ('closed', resource_id))
            elif table == 'forms':
                c.execute(f'UPDATE {table} SET status=? WHERE id=?', ('archived', resource_id))
            else:
                raise ValueError('该资源类型不支持归档操作')

        elif task_type == 'export':
            pass

        else:
            raise ValueError(f'未知操作类型: {task_type}')

        conn.commit()


def _rollback_batch_task(task_id):
    """回滚批量任务"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM batch_task_items WHERE task_id=? AND status=? AND snapshot_json IS NOT NULL',
                     (task_id, 'success'))
            items = c.fetchall()

        rolled = 0
        failed = 0
        for item in items:
            try:
                snapshot = json.loads(item['snapshot_json'])
                resource_type = item['resource_type']
                table = BATCH_RESOURCE_TABLES.get(resource_type)
                if not table or not snapshot:
                    continue

                snapshot_id = snapshot.pop('id', None)
                if not snapshot_id:
                    continue

                snapshot = {k: v for k, v in snapshot.items() if not k.startswith('FOREIGN')}

                with get_db() as conn:
                    c = conn.cursor()
                    set_clause = ', '.join([f'{k}=?' for k in snapshot])
                    values = list(snapshot.values()) + [snapshot_id]
                    c.execute(f'UPDATE {table} SET {set_clause} WHERE id=?', values)
                    conn.commit()

                with get_db() as conn:
                    c = conn.cursor()
                    c.execute('UPDATE batch_task_items SET status=? WHERE id=?', ('rolled_back', item['id']))
                    conn.commit()
                rolled += 1
            except Exception as e:
                logger.error(f"回滚任务项失败: {e}")
                failed += 1

        with get_db() as conn:
            c = conn.cursor()
            c.execute('UPDATE batch_tasks SET status=? WHERE id=?', ('rolled_back', task_id))
            conn.commit()

        return rolled, failed
    except Exception as e:
        logger.error(f"回滚失败: {e}", exc_info=True)
        return 0, 0



@workspace_bp.route('/api/workspace/layout', methods=['GET'])
@login_required
def api_workspace_layout():
    user_id = session['user_id']
    default_layout = [
        {"module_id": "pending_tasks",
         "visible": True, "order": 1},
        {"module_id": "today_stats",
         "visible": True, "order": 2},
        {"module_id": "trend_chart",
         "visible": True, "order": 3},
        {"module_id": "ranking",
         "visible": True, "order": 4},
        {"module_id": "quick_actions",
         "visible": True, "order": 5},
        {"module_id": "recent_activities",
         "visible": True, "order": 6}
    ]
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'SELECT layout_json, theme FROM '
            'user_dashboard_config WHERE user_id=?',
            (user_id,))
        row = c.fetchone()
    if row and row['layout_json']:
        layout = json.loads(row['layout_json'])
        theme = row['theme']
    else:
        layout = default_layout
        theme = 'light'
    return jsonify({
        'success': True,
        'layout': layout,
        'theme': theme
    })


@workspace_bp.route('/api/workspace/layout', methods=['PUT'])
@login_required
def api_workspace_layout_save():
    user_id = session['user_id']
    data = request.get_json(silent=True) or {}
    layout = data.get('layout', [])
    theme = data.get('theme', 'light')
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO user_dashboard_config
            (user_id, layout_json, theme, updated_at)
            VALUES (?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
            layout_json=excluded.layout_json,
            theme=excluded.theme,
            updated_at=CURRENT_TIMESTAMP''',
            (user_id, json.dumps(layout), theme))
        conn.commit()
    return jsonify({'success': True})