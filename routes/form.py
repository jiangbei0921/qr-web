"""
form.py - 表单管理模块
负责表单的创建、编辑、提交和导出。

表单系统是二维码的扩展功能，用户扫描二维码后可以填写表单并提交数据。
适用场景：问卷调查、信息登记、故障报修、意见反馈等。

主要功能：
1. 表单创建：创建自定义字段的表单
2. 表单提交：用户扫码后填写表单数据
3. 提交列表：查看和管理所有提交的数据
4. 数据导出：支持JSON和CSV两种格式导出
5. 表单管理：编辑、删除（软删除到回收站）

数据关系：
- 每个表单（forms）属于一个组织
- 每个表单可以有多条提交记录（form_submissions）
- 表单可以通过二维码关联（qrcodes.associated_form_id）
"""
import json
import csv
import io

from flask import Blueprint, request, jsonify, session, Response
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, check_quota,
    save_version, parse_pagination
)
from routes.workflow_engine import (
    workflow_trigger_after_form_submit
)

form_bp = Blueprint('form', __name__)


@form_bp.route('/api/forms', methods=['GET'])
@login_required
def api_forms_list():
    """列出当前组织的表单"""
    try:
        org_id = session.get('org_id')
        status = (request.args.get('status') or '').strip()
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE f.org_id = ? AND f.is_deleted = 0'
            params = [org_id]
            if status:
                where += ' AND f.status = ?'
                params.append(status)
            c.execute(f'''SELECT f.id, f.org_id, f.form_name, f.status, f.created_at, f.updated_at,
                        (SELECT COUNT(*) FROM form_submissions fs
                         WHERE fs.form_id = f.id) as submission_count
                        FROM forms f {where} ORDER BY f.created_at DESC''', params)
            rows = c.fetchall()
        forms = []
        for r in rows:
            forms.append({
                'id': r['id'], 'org_id': r['org_id'], 'name': r['form_name'],
                'status': r['status'], 'created_at': r['created_at'],
                'updated_at': r['updated_at'], 'submission_count': r['submission_count']
            })
        return jsonify({'success': True, 'forms': forms})
    except Exception as e:
        logger.error(f"表单列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed')}), 500


@form_bp.route('/api/forms', methods=['POST'])
@login_required
def api_forms_create():
    """创建表单（使用当前登录用户的 org_id）"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        name = data.get('name', '未命名表单')
        schema = data.get('schema', {})

        passed, limit, used, msg = check_quota(org_id, 'max_forms')
        if not passed:
            return jsonify({'error': msg, 'quota_key': 'max_forms', 'limit': limit, 'used': used}), 403

        with get_db() as conn:
            c = conn.cursor()
            c.execute('INSERT INTO forms (org_id, form_name, schema_json) VALUES (?, ?, ?)',
                      (org_id, name, json.dumps(schema, ensure_ascii=False)))
            fid = c.lastrowid
            conn.commit()

        logger.info(f"表单创建成功: id={fid}, org_id={org_id}")
        return jsonify({'success': True, 'id': fid})
    except Exception as e:
        logger.error(f"表单创建失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createFailed')}), 500


@form_bp.route('/api/forms/<int:fid>', methods=['GET'])
@login_required
def api_forms_get(fid):
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, form_name, schema_json, created_at FROM forms WHERE id = ? AND org_id = ? AND is_deleted = 0', (fid, org_id))
            row = c.fetchone()
        if not row:
            return jsonify({'error': _t('error.formNotFound')}), 404
        return jsonify({
            'success': True,
            'form': {'id': row['id'], 'name': row['form_name'], 'schema': json.loads(row['schema_json'] or '{}'), 'created_at': row['created_at']}
        })
    except Exception as e:
        logger.error(f"表单查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed')}), 500


@form_bp.route('/api/forms/<int:fid>/submit', methods=['POST'])
@login_required
def api_forms_submit(fid):
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')

        # 先校验表单是否存在且属于当前组织
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM forms WHERE id = ? AND org_id = ?', (fid, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound')}), 404

            c.execute('INSERT INTO form_submissions (form_id, qrcode_id, payload_data) VALUES (?, ?, ?)',
                      (fid, data.get('qrcode_id', 0), json.dumps(data.get('payload', {}), ensure_ascii=False)))
            sid = c.lastrowid
            conn.commit()

        workflow_trigger_after_form_submit(fid, org_id, sid, session.get('user_id'))
        return jsonify({'success': True, 'submission_id': sid})
    except Exception as e:
        logger.error(f"表单提交失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.submitFailed')}), 500

# ============ 活码系统 API ============


@form_bp.route('/api/forms/<int:fid>', methods=['PUT'])
@require_permission('form:edit')
def update_form(fid):
    """更新表单"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        name = (data.get('name') or '').strip()
        schema = data.get('schema', {})
        status = data.get('status', 'active')
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM forms WHERE id=? AND org_id=?', (fid, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound', '表单不存在')}), 404
            
            c.execute('''UPDATE forms SET form_name=?, schema_json=?, status=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND org_id=?''',
                     (name, json.dumps(schema, ensure_ascii=False), status, fid, org_id))
            conn.commit()

        save_version('form', fid, json.dumps({
            'form_name': name, 'schema_json': json.dumps(schema, ensure_ascii=False), 'status': status
        }, ensure_ascii=False), remark='更新表单')

        log_action('update_form', 'form', fid)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"更新表单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500



@form_bp.route('/api/forms/<int:fid>/submissions', methods=['GET'])
@require_permission('form:view')
def list_form_submissions(fid):
    """表单提交列表"""
    try:
        org_id = session.get('org_id')
        page, size, offset = parse_pagination(default_size=20, max_size=100)
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM forms WHERE id=? AND org_id=?', (fid, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound', '表单不存在')}), 404
            
            c.execute('SELECT COUNT(*) FROM form_submissions WHERE form_id=?', (fid,))
            total = c.fetchone()[0]
            
            c.execute('''SELECT fs.*, u.username
                        FROM form_submissions fs LEFT JOIN users u ON fs.submitter_id = u.id
                        WHERE fs.form_id=? ORDER BY fs.created_at DESC LIMIT ? OFFSET ?''',
                     (fid, size, offset))
            rows = c.fetchall()
        
        submissions = []
        for r in rows:
            payload = {}
            try:
                payload = json.loads(r['payload_data']) if r['payload_data'] else {}
            except:
                pass
            submissions.append({
                'id': r['id'], 'payload_data': payload,
                'approval_state': r['approval_state'], 'created_at': r['created_at'],
                'submitter_username': r['username']
            })
        
        return jsonify({'success': True, 'total': total, 'page': page, 'size': size, 'submissions': submissions})
    except Exception as e:
        logger.error(f"表单提交列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@form_bp.route('/api/forms/<int:fid>/export', methods=['GET'])
@require_permission('form:view')
def export_form_submissions(fid):
    """导出表单提交数据
    
    支持两种导出格式：
    1. JSON格式：适合程序处理，返回结构化数据
    2. CSV格式：适合Excel打开，适合非技术人员查看
    
    CSV导出时：
    - 自动收集所有字段名作为表头
    - 使用UTF-8 BOM编码，确保Excel能正确打开中文
    - 复杂字段值会自动转为JSON字符串
    """
    try:
        export_format = request.args.get('format', 'json')
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM forms WHERE id=? AND org_id=?', (fid, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound')}), 404
            
            c.execute('SELECT * FROM form_submissions WHERE form_id=? ORDER BY created_at DESC', (fid,))
            rows = c.fetchall()
        
        data_list = []
        for r in rows:
            try:
                payload = json.loads(r['payload_data']) if r['payload_data'] else {}
                payload['_id'] = r['id']
                payload['_created_at'] = r['created_at']
                data_list.append(payload)
            except Exception as e:
                logger.warning(f"解析提交数据失败: {e}")
                continue
        
        if export_format == 'json':
            return jsonify({'success': True, 'submissions': data_list})
        
        elif export_format == 'csv':
            all_fields = set()
            for d in data_list:
                all_fields.update(d)
            fields = sorted(list(all_fields))
            
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for d in data_list:
                row = {k: v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False) for k, v in d.items()}
                writer.writerow(row)
            
            csv_data = output.getvalue().encode('utf-8-sig')
            return Response(
                csv_data,
                content_type='text/csv; charset=utf-8-sig',
                headers={'Content-Disposition': f'attachment; filename=form_{fid}_export.csv'}
            )
        
        else:
            return jsonify({'error': _t('error.unsupportedFormat', '不支持的导出格式')}), 400
    except Exception as e:
        logger.error(f"表单导出失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.exportFailed', '导出失败')}), 500



@form_bp.route('/api/forms/<int:fid>', methods=['DELETE'])
@require_permission('form:delete')
def delete_form(fid):
    """删除表单（软删除→回收站）
    
    软删除意味着数据不会真正从数据库中删除，
    而是标记为已删除（is_deleted=1），可以在回收站中恢复。
    
    安全限制：如果表单有关联的二维码，不允许删除，防止断链。
    """
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM forms WHERE id=? AND org_id=? AND is_deleted=0', (fid, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.formNotFound', '表单不存在')}), 404

            c.execute('SELECT id FROM qrcodes WHERE associated_form_id=? AND is_deleted=0', (fid,))
            if c.fetchone():
                return jsonify({'error': _t('error.formHasLinkedQrcode', '该表单有关联的二维码，请先解除关联再删除')}), 409

            c.execute('''UPDATE forms SET is_deleted=1, deleted_by=?, deleted_at=datetime('now')
                         WHERE id=? AND org_id=?''',
                     (session.get('user_id'), fid, org_id))
            conn.commit()

        log_action('delete_form', 'form', fid)
        return jsonify({'success': True, 'message': '已移入回收站'})
    except Exception as e:
        logger.error(f"删除表单失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500


# ============ 资产管理 API ============