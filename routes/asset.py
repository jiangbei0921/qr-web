"""jix
asset.py - 资产管理模块
负责资产的创建、管理、二维码绑定和盘点。

资产是系统中需要定期巡检和管理的物理或虚拟物品，例如：
- 设备：机器、电脑、打印机
- 设施：消防器材、电梯、空调
- 物品：库存商品、办公用品

每个资产都可以绑定一个二维码，扫描二维码可以：
1. 查看资产信息
2. 提交巡检记录
3. 创建维修工单
4. 更新资产状态

主要功能：
1. 资产列表：分页、搜索、筛选
2. 资产创建：自动生成绑定二维码和资产编码
3. 资产详情：含巡检统计和最近工单
4. 资产更新：修改属性信息
5. 二维码绑定：将已有二维码绑定到资产
6. 资产盘点：批量查看资产状态
7. 批量导入：通过CSV文件批量导入资产
"""
import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, Config,
    generate_short_code, generate_qrcode,
    image_to_base64, generate_asset_code
)

asset_bp = Blueprint('asset', __name__)


@asset_bp.route('/api/assets', methods=['GET'])
@require_permission('asset:view')
def list_assets():
    """资产列表"""
    try:
        org_id = session.get('org_id')
        page = int(request.args.get('page', 1) or 1)
        size = int(request.args.get('size', 20) or 20)
        keyword = (request.args.get('keyword') or '').strip()
        category = (request.args.get('category') or '').strip()
        status = (request.args.get('status') or '').strip()
        
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE a.org_id = ?'
            params = [org_id]
            if keyword:
                where += ' AND (a.name LIKE ? OR a.asset_code LIKE ?)'
                kw = f'%{keyword}%'
                params.extend([kw, kw])
            if category:
                where += ' AND a.category = ?'
                params.append(category)
            if status:
                where += ' AND a.status = ?'
                params.append(status)
            
            c.execute(f'SELECT COUNT(*) FROM assets a {where}', params)
            total = c.fetchone()[0]
            
            offset = (page - 1) * size
            c.execute(f'''SELECT a.*, q.uuid_short
                        FROM assets a LEFT JOIN qrcodes q ON a.qrcode_id = q.id
                        {where} ORDER BY a.created_at DESC LIMIT ? OFFSET ?''',
                     params + [size, offset])
            rows = c.fetchall()
        
        assets = []
        for r in rows:
            with get_db() as conn:
                c2 = conn.cursor()
                c2.execute('''SELECT inspected_at FROM inspection_records
                            WHERE asset_id = ? ORDER BY inspected_at DESC LIMIT 1''', (r['id'],))
                last = c2.fetchone()
                last_inspection = last['inspected_at'] if last else None
            
            qr_url = f"{Config.BASE_URL}/s/{r['uuid_short']}" if r['uuid_short'] and r['qrcode_id'] else None
            assets.append({
                'id': r['id'], 'name': r['name'], 'asset_code': r['asset_code'],
                'category': r['category'], 'location': r['location'], 'status': r['status'],
                'qrcode_id': r['qrcode_id'], 'purchase_date': r['purchase_date'],
                'value': r['value'], 'responsible_user_id': r['responsible_user_id'],
                'created_at': r['created_at'], 'last_inspection': last_inspection,
                'qr_url': qr_url
            })
        
        return jsonify({'success': True, 'total': total, 'assets': assets})
    except Exception as e:
        logger.error(f"资产列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@asset_bp.route('/api/assets', methods=['POST'])
@require_permission('asset:manage')
def create_asset():
    """创建资产（自动生成绑定二维码和资产编码）
    
    创建资产时，系统会自动执行以下操作：
    1. 生成唯一的资产编码（asset_code），如 ASSET-2024-0001
    2. 自动创建一个活码（动态二维码）绑定到该资产
    3. 扫描二维码可以查看资产信息、提交巡检、创建工单
    
    这样用户拿到资产后，贴上一个二维码，
    用手机扫码就能快速查看资产所有信息。
    """
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        name = (data.get('name') or '').strip()
        category = (data.get('category') or '').strip()
        location = data.get('location', '') or ''
        purchase_date = data.get('purchase_date', '') or ''
        value = float(data.get('value', 0) or 0)
        responsible_user_id = data.get('responsible_user_id')
        description = data.get('description', '') or ''
        auto_create_qrcode = data.get('auto_create_qrcode', True)
        
        if not name:
            return jsonify({'error': _t('error.assetNameRequired', '资产名称不能为空')}), 400
            
        asset_code = generate_asset_code()
        qrcode_id = None
        qr_url = None
        qrcode_base64 = None
        
        if auto_create_qrcode:
            # 为资产自动生成一个专属二维码
            short_code = generate_short_code()
            qr_url = f"{Config.BASE_URL}/s/{short_code}"
            
            from urllib.parse import urlparse
            if not request.referrer or 'localhost' in request.referrer or '127.0.0.1' in request.referrer:
                target_url = f"{Config.BASE_URL}/s/{short_code}"
            else:
                parsed = urlparse(request.referrer)
                base = f"{parsed.scheme}://{parsed.netloc}"
                target_url = f"{base}/s/{short_code}"
            style_config = {}
            
            img = generate_qrcode(qr_url, style_config)
            qrcode_base64 = image_to_base64(img)
            
            with get_db() as conn:
                c = conn.cursor()
                # 创建动态链接（活码）
                c.execute('''INSERT INTO dynamic_links
                            (org_id, title, short_code, target_url, target_type,
                            status, scan_count, created_by)
                            VALUES (?,?,?,?,?,?,?,?)''',
                         (org_id, f"资产-{name}", short_code, target_url, 'asset', 'active', 0, user_id))
                dynamic_link_id = c.lastrowid
                # 创建二维码记录
                c.execute('''INSERT INTO qrcodes (org_id, uuid_short, title, biz_type)
                            VALUES (?,?,?,?)''',
                         (org_id, short_code, f"资产-{name}", 'asset'))
                qrcode_id = c.lastrowid
                # 关联动态链接和二维码
                c.execute('UPDATE dynamic_links SET qrcode_id = ? WHERE id = ?', (qrcode_id, dynamic_link_id))
                conn.commit()
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO assets
                        (org_id, name, asset_code, category, location, status,
                        description, qrcode_id, purchase_date, value,
                        responsible_user_id, created_by)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (org_id, name, asset_code, category, location, 'normal',
                      description, qrcode_id, purchase_date, value,
                      responsible_user_id, user_id))
            asset_id = c.lastrowid
            conn.commit()
        
        log_action('create_asset', 'asset', asset_id)
        return jsonify({
            'success': True, 'asset_id': asset_id, 'asset_code': asset_code,
            'qrcode_id': qrcode_id, 'qr_url': qr_url, 'qrcode_base64': qrcode_base64
        })
    except Exception as e:
        logger.error(f"创建资产失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@asset_bp.route('/api/assets/<int:asset_id>', methods=['GET'])
@require_permission('asset:view')
def get_asset_detail(asset_id):
    """资产详情"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM assets WHERE id=? AND org_id=?', (asset_id, org_id))
            asset = c.fetchone()
            if not asset:
                return jsonify({'error': _t('error.assetNotFound', '资产不存在')}), 404
            
            qrcode = None
            if asset['qrcode_id']:
                c.execute('SELECT id, uuid_short, scan_count FROM qrcodes WHERE id=?', (asset['qrcode_id'],))
                q = c.fetchone()
                if q:
                    qrcode = {
                        'id': q['id'], 'uuid_short': q['uuid_short'],
                        'scan_count': q['scan_count'],
                        'qr_url': f"{Config.BASE_URL}/s/{q['uuid_short']}"
                    }
            
            c.execute('SELECT COUNT(*) FROM inspection_records WHERE asset_id=?', (asset_id,))
            total = c.fetchone()[0]
            
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            c.execute('SELECT COUNT(*) FROM inspection_records WHERE asset_id=? AND inspected_at >= ?', (asset_id, thirty_days_ago))
            last_30_days = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM inspection_records WHERE asset_id=? AND result != ?', (asset_id, 'normal'))
            abnormal_count = c.fetchone()[0]
            
            c.execute('SELECT * FROM inspection_records WHERE asset_id=? ORDER BY inspected_at DESC LIMIT 1', (asset_id,))
            last_inspection = c.fetchone()
            
            c.execute('SELECT id, title, status, created_at FROM workorders WHERE asset_id=? ORDER BY created_at DESC LIMIT 5', (asset_id,))
            recent_workorders = [dict(r) for r in c.fetchall()]
        
        inspection_stats = {
            'total': total, 'last_30_days': last_30_days, 'abnormal_count': abnormal_count,
            'last_inspection': dict(last_inspection) if last_inspection else None
        }
        
        return jsonify({
            'success': True, 'asset': dict(asset),
            'qrcode': qrcode, 'inspection_stats': inspection_stats,
            'recent_workorders': recent_workorders
        })
    except Exception as e:
        logger.error(f"资产详情查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@asset_bp.route('/api/assets/<int:asset_id>', methods=['PUT'])
@require_permission('asset:manage')
def update_asset(asset_id):
    """更新资产"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        name = (data.get('name') or '').strip()
        category = (data.get('category') or '').strip()
        location = data.get('location', '') or ''
        purchase_date = data.get('purchase_date', '') or ''
        value = float(data.get('value', 0) or 0)
        responsible_user_id = data.get('responsible_user_id')
        description = data.get('description', '') or ''
        status = data.get('status', 'normal') or 'normal'
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM assets WHERE id=? AND org_id=?', (asset_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.assetNotFound', '资产不存在')}), 404
            
            c.execute('''UPDATE assets SET
                        name=?, category=?, location=?, purchase_date=?,
                        value=?, responsible_user_id=?, description=?, status=?,
                        updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND org_id=?''',
                     (name, category, location, purchase_date, value,
                      responsible_user_id, description, status, asset_id, org_id))
            conn.commit()
        
        log_action('update_asset', 'asset', asset_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"更新资产失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed')}), 500



@asset_bp.route('/api/assets/<int:asset_id>/bind-qrcode', methods=['POST'])
@require_permission('asset:manage')
def bind_asset_qrcode(asset_id):
    """绑定已有二维码"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        qrcode_id = data.get('qrcode_id')
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM assets WHERE id=? AND org_id=?', (asset_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.assetNotFound', '资产不存在')}), 404
            
            c.execute('SELECT id, org_id FROM qrcodes WHERE id=?', (qrcode_id,))
            qr = c.fetchone()
            if not qr or qr['org_id'] != org_id:
                return jsonify({'error': _t('error.qrcodeOrAssetNotFound', '二维码不存在或不匹配')}), 404
            
            c.execute('UPDATE assets SET qrcode_id=? WHERE id=? AND org_id=?', (qrcode_id, asset_id, org_id))
            conn.commit()
        
        log_action('bind_qrcode', 'asset', asset_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"绑定二维码失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.bindFailed')}), 500



@asset_bp.route('/api/assets/inventory', methods=['GET'])
@require_permission('asset:view')
def asset_inventory():
    """资产盘点列表"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT a.id, a.name, a.asset_code, a.location, a.status,
                               a.qrcode_id, q.uuid_short,
                               (SELECT inspected_at FROM inspection_records
                                WHERE asset_id = a.id ORDER BY inspected_at DESC LIMIT 1) as last_inspection,
                               (SELECT result FROM inspection_records
                                WHERE asset_id = a.id ORDER BY inspected_at DESC LIMIT 1) as last_result
                        FROM assets a LEFT JOIN qrcodes q ON a.qrcode_id = q.id
                        WHERE a.org_id = ? ORDER BY a.category, a.name''', (org_id,))
            rows = c.fetchall()
        
        assets = []
        for r in rows:
            qr_url = f"{Config.BASE_URL}/s/{r['uuid_short']}" if r['uuid_short'] else None
            assets.append({
                'id': r['id'], 'name': r['name'], 'asset_code': r['asset_code'],
                'location': r['location'], 'status': r['status'],
                'last_inspection': r['last_inspection'],
                'inspection_result': r['last_result'],
                'qr_url': qr_url
            })
        
        return jsonify({'success': True, 'assets': assets})
    except Exception as e:
        logger.error(f"资产盘点查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@asset_bp.route('/api/assets/batch-import', methods=['POST'])
@require_permission('asset:manage')
def batch_import_assets():
    """批量导入资产（CSV文件）"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        if 'file' not in request.files:
            return jsonify({'error': _t('error.fileRequired', '未上传文件')}), 400
        
        file = request.files['file']
        if not file:
            return jsonify({'error': _t('error.fileEmpty', '文件为空')}), 400
        
        stream = io.StringIO(file.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        
        imported = 0
        failed = 0
        errors = []
        row_num = 2
        
        with get_db() as conn:
            c = conn.cursor()
            batch_size = 100
            for i, row in enumerate(reader):
                try:
                    name = (row.get('name') or '').strip()
                    if not name:
                        errors.append(f'第{row_num}行：名称为空')
                        failed += 1
                        row_num += 1
                        continue
                    
                    category = (row.get('category') or '').strip()
                    location = (row.get('location') or '').strip()
                    purchase_date = (row.get('purchase_date') or '').strip()
                    value_str = (row.get('value') or '0').strip()
                    value = float(value_str) if value_str else 0
                    
                    asset_code = generate_asset_code()
                    c.execute('''INSERT INTO assets
                                (org_id, name, asset_code, category, location,
                                purchase_date, value, created_by)
                                VALUES (?,?,?,?,?,?,?,?)''',
                             (org_id, name, asset_code, category, location,
                              purchase_date, value, user_id))
                    imported += 1
                except Exception as e:
                    errors.append(f'第{row_num}行：{str(e)}')
                    failed += 1
                row_num += 1
                if (i + 1) % batch_size == 0:
                    conn.commit()
            conn.commit()
        
        if imported > 0:
            log_action('batch_import_assets', 'asset', None, {'imported': imported, 'failed': failed})
        return jsonify({
            'success': True, 'imported': imported,
            'failed': failed, 'errors': errors
        })
    except Exception as e:
        logger.error(f"批量导入资产失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.importFailed', '导入失败')}), 500


# ============ 巡检系统 API ============