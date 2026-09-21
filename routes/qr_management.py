"""
qr_management.py - 二维码管理模块（生成能力已迁移至 routes/qrkit 新内核）
这是系统的核心模块，负责二维码的生成、管理和扫码跳转。

主要功能：
1. 活码（动态链接）：创建可修改目标的二维码，支持扫码统计
2. 扫码跳转：扫二维码后自动跳转到目标URL，并记录扫码数据
3. 二维码管理：列表、详情、编辑、删除、归档、标签、批量导出
4. （静态/批量生成已迁移至 routes/qrkit 新内核）

关键概念：
- 活码（Dynamic Link）：二维码指向一个短链接，可以通过修改短链接的目标来改变扫码结果
- 短码（Short Code）：活码的短链接标识，如 /s/abc123
- 扫码日志（Scan Log）：每次扫码都会记录设备、浏览器、IP等信息
- 生命周期：二维码有 draft→active→archived 等状态
"""
import json
import csv
import io
import os
import uuid
import urllib.parse
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify, session, redirect
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, generate_short_code,
    Config, generate_qrcode,
    image_to_base64,
    safe_filename, check_quota, update_org_quota,
    parse_user_agent, save_version, workflow_trigger_after_scan,
    workflow_trigger_after_qrcode_create,
    LIFECYCLE_LABELS, LIFECYCLE_COLORS, LIFECYCLE_TRANSITIONS,
    validate_transition, UPLOAD_FOLDER, DATABASE
)

qr_management_bp = Blueprint('qrcode', __name__)


def _get_qrcode_by_id_cursor(c, qrcode_id, org_id, check_deleted=True):
    """使用已有cursor获取二维码记录（用于事务内部复用）"""
    if check_deleted:
        c.execute('SELECT * FROM qrcodes WHERE id=? AND org_id=? AND is_deleted=0', (qrcode_id, org_id))
    else:
        c.execute('SELECT * FROM qrcodes WHERE id=? AND org_id=?', (qrcode_id, org_id))
    return c.fetchone()


def _get_qrcode_by_id(qrcode_id, org_id, check_deleted=True):
    """根据ID获取二维码记录

    参数：
        qrcode_id: 二维码ID
        org_id: 组织ID
        check_deleted: 是否排除已删除的记录（默认True）

    返回：
        sqlite3.Row 或 None
    """
    with get_db() as conn:
        return _get_qrcode_by_id_cursor(conn.cursor(), qrcode_id, org_id, check_deleted)


def _get_scan_stats(c, qrcode_id):
    """获取二维码扫码统计

    参数：
        c: 数据库cursor
        qrcode_id: 二维码ID

    返回：
        dict: {today, week, month, total}
    """
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM scan_logs WHERE qrcode_id=? AND date(scan_time)=?", (qrcode_id, today))
    today_scans = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM scan_logs WHERE qrcode_id=? AND scan_time >= datetime('now','-7 days')", (qrcode_id,))
    week_scans = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM scan_logs WHERE qrcode_id=? AND scan_time >= datetime('now','-30 days')", (qrcode_id,))
    month_scans = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM scan_logs WHERE qrcode_id=?", (qrcode_id,))
    total_scans = c.fetchone()[0]

    return {
        'today': today_scans,
        'week': week_scans,
        'month': month_scans,
        'total': total_scans
    }


@qr_management_bp.route('/s/<short_code>')
def dynamic_redirect(short_code):
    """活码扫码跳转路由（无需登录，任何人都可以扫码访问）
    
    这是整个系统最核心的功能——当用户用手机扫描二维码后，
    系统会执行以下流程：

    1. 查找短码对应的动态链接
    2. 检查二维码状态（是否有效、是否过期、是否达到扫码上限）
    3. 记录扫码日志（设备信息、浏览器、IP等）
    4. 更新扫码计数
    5. 检查是否触发扫码阈值工作流
    6. 如果关联了资产，检查是否需要巡检
    7. 最终重定向到目标URL

    这个过程对用户来说只是一瞬间的跳转，但背后做了很多工作。
    """
    try:
        with get_db() as conn:
            c = conn.cursor()
            # 查找有效的动态链接
            c.execute('SELECT * FROM dynamic_links WHERE short_code=? AND status=?', (short_code, 'active'))
            link = c.fetchone()
        
        # 情况1：链接不存在或不活跃
        if not link:
            c.execute('SELECT * FROM dynamic_links WHERE short_code=?', (short_code,))
            link_any = c.fetchone()
            if not link_any:
                # 链接完全不存在，被删除了
                return '<html><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#475569;background:#000;"><div style="text-align:center;"><h1 style="color:#EF4444;">二维码无效</h1><p>该二维码不存在或已被删除</p></div></body></html>', 404
            # 链接被停用了
            return '<html><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#475569;background:#000;"><div style="text-align:center;"><h1 style="color:#EF4444;">二维码已失效</h1><p>该二维码已被停用</p></div></body></html>', 404
        
        # 情况2：检查是否过期
        if link['expire_time']:
            from datetime import datetime as dt
            try:
                expire = dt.strptime(link['expire_time'], '%Y-%m-%d %H:%M:%S')
                if expire < dt.now():
                    # 已过期，自动将状态改为expired
                    with get_db() as conn:
                        conn.cursor().execute('UPDATE dynamic_links SET status=? WHERE id=?', ('expired', link['id']))
                        conn.commit()
                    return '<html><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#475569;background:#000;"><div style="text-align:center;"><h1 style="color:#EF4444;">二维码已过期</h1><p>该二维码的有效期已过</p></div></body></html>', 410
            except (ValueError, TypeError):
                pass  # 过期时间格式错误，忽略
        
        # 情况3：检查扫码次数是否达到上限
        if link['max_scans'] > 0 and link['scan_count'] >= link['max_scans']:
            with get_db() as conn:
                conn.cursor().execute('UPDATE dynamic_links SET status=? WHERE id=?', ('exhausted', link['id']))
                conn.commit()
            return '<html><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#475569;background:#000;"><div style="text-align:center;"><h1 style="color:#EF4444;">扫码次数已达上限</h1><p>该二维码已达到最大扫码次数</p></div></body></html>', 410
        
        # 解析用户设备信息（手机还是电脑、什么浏览器、什么操作系统）
        ua = request.headers.get('User-Agent', '')
        device, os_name, browser = parse_user_agent(ua)
        
        # 记录扫码日志并更新计数
        with get_db() as conn:
            c = conn.cursor()
            # 插入扫码日志
            c.execute('''INSERT INTO scan_logs (qrcode_id, dynamic_link_id, ip, device, browser, os, user_agent)
                        VALUES (?,?,?,?,?,?,?)''',
                     (link['qrcode_id'], link['id'], request.remote_addr, device, browser, os_name, ua))
            # 更新动态链接的扫码计数
            c.execute('UPDATE dynamic_links SET scan_count = scan_count + 1 WHERE id=?', (link['id'],))
            # 如果有关联的二维码，也更新其扫码计数
            if link['qrcode_id']:
                c.execute('UPDATE qrcodes SET scan_count = scan_count + 1 WHERE id=?', (link['qrcode_id'],))
            conn.commit()

            # 检查扫码阈值触发工作流
            if link['qrcode_id'] and link['org_id']:
                c.execute('SELECT scan_count FROM qrcodes WHERE id=?', (link['qrcode_id'],))
                qr = c.fetchone()
                if qr:
                    scan_count = qr['scan_count']
                    # 触发扫码后工作流
                    workflow_trigger_after_scan(link['qrcode_id'], link['org_id'], scan_count)
                    # 检查是否达到扫码阈值
                    cfg = json.loads(link['trigger_config'] or '{}') if link.get('trigger_config') else {}
                    threshold = cfg.get('scan_threshold', 0)
                    if threshold > 0 and scan_count >= threshold:
                        event = {
                            'qrcode_id': link['qrcode_id'],
                            'qrcode_title': link['title'] or '',
                            'scan_count': scan_count,
                            'threshold': threshold
                        }
                        try:
                            from routes.workflow_engine import WorkflowEngine
                            WorkflowEngine.trigger_event(link['org_id'], 'qrcode:scan_threshold', event)
                        except ImportError:
                            pass
        
        # 如果二维码关联了资产，检查是否需要巡检
        target_url = str(link['target_url'] or '')
        if link['org_id'] and link['qrcode_id']:
            try:
                with get_db() as conn:
                    c2 = conn.cursor()
                    c2.execute('''SELECT a.id, a.name FROM assets a
                                WHERE a.qrcode_id=? AND a.org_id=?''',
                             (link['qrcode_id'], link['org_id']))
                    asset = c2.fetchone()
                    if asset:
                        # 在URL中添加资产ID参数
                        url_parts = list(urllib.parse.urlparse(target_url))
                        qs = dict(urllib.parse.parse_qsl(url_parts[4]))
                        qs['asset_id'] = str(asset['id'])
                        # 检查是否有逾期的巡检计划
                        c2.execute('''SELECT ip.id FROM inspection_plans ip
                                    WHERE ip.asset_id=? AND ip.is_active=1
                                    AND ip.org_id=?''',
                                 (asset['id'], link['org_id']))
                        plans = c2.fetchall()
                        if plans:
                            today = datetime.now().strftime('%Y-%m-%d')
                            for p in plans:
                                if p['last_completed']:
                                    # 计算下次巡检日期
                                    due = (datetime.strptime(p['last_completed'][:10], '%Y-%m-%d') + timedelta(days=p['frequency_days'])).strftime('%Y-%m-%d')
                                    if due < today:
                                        qs['needs_inspection'] = '1'
                                        break
                                else:
                                    # 从未巡检过，标记需要巡检
                                    qs['needs_inspection'] = '1'
                                    break
                        url_parts[4] = urllib.parse.urlencode(qs)
                        target_url = urllib.parse.urlunparse(url_parts)
            except Exception as e:
                logger.warning(f"扫码资产巡检检查失败: {e}")
        
        # 最终重定向到目标URL
        return redirect(target_url)
    
    except Exception as e:
        logger.error(f"活码跳转失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.serverError', '服务器错误，请稍后重试')}), 500


@qr_management_bp.route('/api/dynamic-links/create', methods=['POST'])
@login_required
def create_dynamic_link():
    """创建活码（动态链接二维码）

    这是系统最核心的功能之一。
    活码与传统静态码的区别：
    - 静态码：二维码内容固定，修改内容需要重新生成图片
    - 活码：二维码指向一个短链接，修改短链接的目标即可改变扫码结果，
      不需要重新打印二维码。适合贴在印刷品、海报上长期使用。

    创建流程：
    1. 检查配额（是否超过最大二维码数量限制）
    2. 生成唯一的短码（short_code）
    3. 创建动态链接记录（dynamic_links 表）
    4. 创建二维码记录（qrcodes 表）
    5. 将两个记录关联起来
    6. 生成二维码图片并返回
    7. 触发工作流（如果有配置的话）
    """
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        title = (data.get('title') or '').strip()

        # 检查配额：是否超过最大二维码数量限制
        passed, limit, used, msg = check_quota(org_id, 'max_qrcodes')
        if not passed:
            return jsonify({'error': msg, 'quota': {'limit': limit, 'used': used}, 'upgrade_url': '/#subscription'}), 403
        target_url = (data.get('target_url') or '').strip()
        target_type = data.get('target_type', 'url')
        expire_time = data.get('expire_time')  # 过期时间（可选）
        max_scans = int(data.get('max_scans', 0) or 0)  # 最大扫码次数（0=不限制）
        style_config = data.get('style_config', {}) or {}  # 二维码样式
        
        if not title:
            return jsonify({'error': _t('error.titleRequired')}), 400
        if not target_url:
            return jsonify({'error': _t('error.targetUrlRequired')}), 400
        
        # 生成唯一的短码（6位随机字符串），作为活码的标识
        short_code = generate_short_code()
        # 构建完整的短链接地址
        qr_url = f"{Config.BASE_URL}/s/{short_code}"
        
        # 生成二维码图片
        img = generate_qrcode(qr_url, style_config)
        img_base64 = image_to_base64(img)
        
        with get_db() as conn:
            c = conn.cursor()
            # 第一步：创建动态链接记录
            c.execute('''INSERT INTO dynamic_links
                        (short_code, org_id, title, target_url, target_type, expire_time, max_scans, created_by)
                        VALUES (?,?,?,?,?,?,?,?)''',
                     (short_code, org_id, title, target_url, target_type, expire_time, max_scans, session.get('user_id')))
            link_id = c.lastrowid
            
            # 第二步：创建二维码记录
            c.execute('''INSERT INTO qrcodes
                        (uuid_short, org_id, title, content_json, style_config, creator_id, dynamic_link_id)
                        VALUES (?,?,?,?,?,?,?)''',
                     (short_code, org_id, title, json.dumps({'url': qr_url}, ensure_ascii=False),
                      json.dumps(style_config, ensure_ascii=False), session.get('user_id'), link_id))
            qrcode_id = c.lastrowid
            
            # 第三步：将两个记录关联起来
            c.execute('UPDATE dynamic_links SET qrcode_id=? WHERE id=?', (qrcode_id, link_id))
            conn.commit()
        
        log_action('create_dynamic_link', 'dynamic_link', link_id, {'title': title})
        logger.info(f"活码创建成功: link_id={link_id}, short_code={short_code}")

        # 触发工作流（如果有配置二维码创建后触发的工作流）
        workflow_trigger_after_qrcode_create(qrcode_id, org_id, title, session.get('user_id'))
        # 更新配额使用量
        update_org_quota(org_id, 'max_qrcodes', 1)
        
        return jsonify({
            'success': True,
            'short_code': short_code,
            'qr_url': qr_url,
            'qrcode_base64': f'data:image/png;base64,{img_base64}',
            'dynamic_link_id': link_id,
            'qrcode_id': qrcode_id
        })
    
    except Exception as e:
        logger.error(f"活码创建失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createRetryFailed')}), 500


@qr_management_bp.route('/api/dynamic-links/<int:link_id>', methods=['PUT'])
@login_required
def update_dynamic_link(link_id):
    """修改活码目标"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM dynamic_links WHERE id=? AND org_id=?', (link_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.dynamicLinkNotFound')}), 404
            
            target_url = (data.get('target_url') or '').strip()
            title = (data.get('title') or '').strip()
            expire_time = data.get('expire_time')
            max_scans = int(data.get('max_scans', 0) or 0)
            status = data.get('status')
            
            c.execute('''UPDATE dynamic_links
                        SET target_url=?, title=?, expire_time=?, max_scans=?, status=COALESCE(?, status), updated_at=CURRENT_TIMESTAMP
                        WHERE id=?''',
                     (target_url, title, expire_time, max_scans, status, link_id))
            conn.commit()
        
        log_action('update_dynamic_link', 'dynamic_link', link_id)
        return jsonify({'success': True})
    
    except Exception as e:
        logger.error(f"活码修改失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.modifyFailed')}), 500


@qr_management_bp.route('/api/dynamic-links/<int:link_id>/toggle', methods=['POST'])
@login_required
def toggle_dynamic_link(link_id):
    """启停活码"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT status FROM dynamic_links WHERE id=? AND org_id=?', (link_id, org_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': _t('error.dynamicLinkNotFound')}), 404
            
            new_status = 'disabled' if row['status'] == 'active' else 'active'
            c.execute('UPDATE dynamic_links SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (new_status, link_id))
            conn.commit()
        
        log_action('toggle_dynamic_link', 'dynamic_link', link_id)
        return jsonify({'success': True, 'status': new_status})
    
    except Exception as e:
        logger.error(f"活码启停失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed')}), 500


@qr_management_bp.route('/api/dynamic-links/<int:link_id>', methods=['DELETE'])
@login_required
def delete_dynamic_link(link_id):
    """删除活码（软删除）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT qrcode_id FROM dynamic_links WHERE id=? AND org_id=?', (link_id, org_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': _t('error.dynamicLinkNotFound')}), 404
            
            c.execute("UPDATE dynamic_links SET status='deleted' WHERE id=?", (link_id,))
            if row['qrcode_id']:
                c.execute('UPDATE qrcodes SET is_active=0 WHERE id=?', (row['qrcode_id'],))
            conn.commit()
        
        log_action('delete_dynamic_link', 'dynamic_link', link_id)
        return jsonify({'success': True})
    
    except Exception as e:
        logger.error(f"活码删除失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500


@qr_management_bp.route('/api/dynamic-links/list', methods=['GET'])
@login_required
def list_dynamic_links():
    """活码列表"""
    try:
        org_id = session.get('org_id')
        page = int(request.args.get('page', 1) or 1)
        size = int(request.args.get('size', 20) or 20)
        status = request.args.get('status')
        keyword = (request.args.get('keyword') or '').strip()
        
        with get_db() as conn:
            c = conn.cursor()
            where = "WHERE org_id=? AND status != 'deleted'"
            params = [org_id]
            
            if status:
                where += ' AND status=?'
                params.append(status)
            if keyword:
                where += ' AND (title LIKE ? OR short_code LIKE ?)'
                params.extend([f'%{keyword}%', f'%{keyword}%'])
            
            c.execute(f'SELECT COUNT(*) FROM dynamic_links {where}', params)
            total = c.fetchone()[0]
            
            offset = (page - 1) * size
            c.execute(f'SELECT * FROM dynamic_links {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
                     params + [size, offset])
            rows = c.fetchall()
        
        links = []
        for r in rows:
            is_expired = False
            if r['expire_time']:
                try:
                    from datetime import datetime as dt
                    expire = dt.strptime(r['expire_time'], '%Y-%m-%d %H:%M:%S')
                    is_expired = expire < dt.now()
                except (ValueError, TypeError):
                    pass
            links.append({
                'id': r['id'], 'short_code': r['short_code'], 'title': r['title'],
                'target_url': r['target_url'], 'target_type': r['target_type'],
                'status': r['status'], 'scan_count': r['scan_count'], 'max_scans': r['max_scans'],
                'expire_time': r['expire_time'], 'created_at': r['created_at'],
                'updated_at': r['updated_at'],
                'qr_url': f"{Config.BASE_URL}/s/{r['short_code']}",
                'is_expired': is_expired
            })
        
        return jsonify({'success': True, 'total': total, 'links': links})
    
    except Exception as e:
        logger.error(f"活码列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/dynamic-links/<int:link_id>', methods=['GET'])
@login_required
def get_dynamic_link(link_id):
    """活码详情"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM dynamic_links WHERE id=? AND org_id=?', (link_id, org_id))
            link = c.fetchone()
            if not link:
                return jsonify({'error': _t('error.dynamicLinkNotFound', '活码不存在')}), 404
            
            c.execute('''SELECT scan_time, ip, device, browser, os, country
                        FROM scan_logs WHERE dynamic_link_id=? ORDER BY scan_time DESC LIMIT 10''', (link_id,))
            logs = [dict(r) for r in c.fetchall()]
        
        return jsonify({
            'success': True,
            'link': {
                'id': link['id'], 'short_code': link['short_code'], 'title': link['title'],
                'target_url': link['target_url'], 'target_type': link['target_type'],
                'status': link['status'], 'scan_count': link['scan_count'], 'max_scans': link['max_scans'],
                'expire_time': link['expire_time'], 'created_at': link['created_at'],
                'updated_at': link['updated_at'], 'qrcode_id': link['qrcode_id'],
                'qr_url': f"{Config.BASE_URL}/s/{link['short_code']}"
            },
            'recent_logs': logs
        })
    
    except Exception as e:
        logger.error(f"活码详情查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/list', methods=['GET'])
@login_required
def list_qrcodes_enhanced():
    """二维码列表（增强版）"""
    try:
        org_id = session.get('org_id')
        page = int(request.args.get('page', 1) or 1)
        size = int(request.args.get('size', 20) or 20)
        keyword = (request.args.get('keyword') or '').strip()
        status = request.args.get('status')
        category = (request.args.get('category') or '').strip()
        archive_status = int(request.args.get('archive_status', 0) or 0)
        
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE q.org_id=? AND q.is_active=1 AND q.is_deleted=0'
            params = [org_id]
            
            if keyword:
                where += ' AND q.title LIKE ?'
                params.append(f'%{keyword}%')
            if status:
                where += ' AND q.current_status=?'
                params.append(status)
            if category:
                where += ' AND q.category=?'
                params.append(category)
            if archive_status is not None:
                where += ' AND q.archive_status=?'
                params.append(archive_status)
            
            c.execute(f'SELECT COUNT(*) FROM qrcodes q {where}', params)
            total = c.fetchone()[0]
            
            offset = (page - 1) * size
            c.execute(f'''SELECT q.*, dl.short_code, dl.status as link_status,
                        dl.scan_count as link_scan_count, dl.expire_time, dl.max_scans
                        FROM qrcodes q LEFT JOIN dynamic_links dl ON dl.qrcode_id = q.id
                        {where} ORDER BY q.created_at DESC LIMIT ? OFFSET ?''',
                     params + [size, offset])
            rows = c.fetchall()
        
        qrcodes = []
        for r in rows:
            qr_url = None
            if r['short_code']:
                qr_url = f"{Config.BASE_URL}/s/{r['short_code']}"
            qrcodes.append({
                'id': r['id'], 'uuid_short': r['uuid_short'], 'title': r['title'],
                'category': r['category'], 'current_status': r['current_status'],
                'scan_count': r['scan_count'], 'is_active': r['is_active'],
                'archive_status': r['archive_status'], 'creator_id': r['creator_id'],
                'created_at': r['created_at'], 'updated_at': r['updated_at'],
                'dynamic_link_id': r['dynamic_link_id'], 'qr_url': qr_url
            })
        
        return jsonify({'success': True, 'total': total, 'qrcodes': qrcodes})
    
    except Exception as e:
        logger.error(f"二维码列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/detail', methods=['GET'])
@login_required
def get_qrcode_detail(qrcode_id):
    """二维码详情"""
    try:
        org_id = session.get('org_id')
        qr = _get_qrcode_by_id(qrcode_id, org_id, check_deleted=False)
        if not qr:
            return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404

        with get_db() as conn:
            c = conn.cursor()
            scan_stats = _get_scan_stats(c, qrcode_id)

            c.execute('SELECT * FROM scan_logs WHERE qrcode_id=? ORDER BY scan_time DESC LIMIT 20', (qrcode_id,))
            recent_logs = [dict(r) for r in c.fetchall()]
            
            dynamic_link = None
            if qr['dynamic_link_id']:
                c.execute('SELECT * FROM dynamic_links WHERE id=?', (qr['dynamic_link_id'],))
                dl = c.fetchone()
                if dl:
                    dynamic_link = dict(dl)
            
            if qr['associated_form_id']:
                c.execute('SELECT id, form_name, created_at FROM forms WHERE id=?', (qr['associated_form_id'],))
                f = c.fetchone()
                associated_form = dict(f) if f else None
            else:
                associated_form = None
            
            c.execute('SELECT * FROM audit_logs WHERE target_type=? AND target_id=? ORDER BY created_at DESC LIMIT 10', ('qrcode', qrcode_id))
            audit_logs = [dict(r) for r in c.fetchall()]
        
        return jsonify({
            'success': True,
            'qrcode': dict(qr),
            'stats': {
                'today_scans': scan_stats['today'],
                'week_scans': scan_stats['week'],
                'month_scans': scan_stats['month'],
                'total_scans': scan_stats['total']
            },
            'recent_logs': recent_logs,
            'dynamic_link': dynamic_link,
            'associated_form': associated_form,
            'audit_logs': audit_logs
        })
    
    except Exception as e:
        logger.error(f"二维码详情查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/toggle', methods=['POST'])
@login_required
def toggle_qrcode(qrcode_id):
    """停用/启用二维码"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT is_active FROM qrcodes WHERE id=? AND org_id=?', (qrcode_id, org_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404
            
            new_status = 0 if row['is_active'] else 1
            c.execute('UPDATE qrcodes SET is_active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (new_status, qrcode_id))
            conn.commit()
        
        log_action('toggle_qrcode', 'qrcode', qrcode_id)
        return jsonify({'success': True, 'is_active': new_status})
    
    except Exception as e:
        logger.error(f"二维码切换失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.operationFailed', '操作失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/archive', methods=['POST'])
@login_required
def archive_qrcode(qrcode_id):
    """归档二维码"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM qrcodes WHERE id=? AND org_id=?', (qrcode_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404
            
            c.execute('UPDATE qrcodes SET archive_status=1, updated_at=CURRENT_TIMESTAMP WHERE id=?', (qrcode_id,))
            conn.commit()
        
        log_action('archive_qrcode', 'qrcode', qrcode_id)
        return jsonify({'success': True})
    
    except Exception as e:
        logger.error(f"二维码归档失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.archiveFailed', '归档失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>', methods=['PUT'])
@login_required
def update_qrcode(qrcode_id):
    """更新二维码（含版本快照保存）"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')

        qr = _get_qrcode_by_id(qrcode_id, org_id, check_deleted=True)
        if not qr:
            return jsonify({'error': _t('error.qrcodeNotFound')}), 404

        with get_db() as conn:
            c = conn.cursor()
            updates = []
            params = []
            snapshot = {}

            title = data.get('title')
            if title is not None:
                updates.append('title = ?')
                params.append(title.strip())
                snapshot['title'] = title.strip()

            category = data.get('category')
            if category is not None:
                updates.append('category = ?')
                params.append(category.strip())
                snapshot['category'] = category.strip()

            content_json = data.get('content_json')
            if content_json is not None:
                content_str = json.dumps(content_json, ensure_ascii=False)
                updates.append('content_json = ?')
                params.append(content_str)
                snapshot['content_json'] = content_str

            style_config = data.get('style_config')
            if style_config is not None:
                style_str = json.dumps(style_config, ensure_ascii=False)
                updates.append('style_config = ?')
                params.append(style_str)
                snapshot['style_config'] = style_str

            if not updates:
                return jsonify({'error': _t('error.noFieldsToUpdate', '没有需要更新的字段')}), 400

            ALLOWED_QRCODE_FIELDS = {
                'title', 'category', 'current_status',
                'is_active', 'archive_status', 'tags'
            }
            for upd in updates:
                field = upd.split(' = ')[0]
                if field not in ALLOWED_QRCODE_FIELDS:
                    return jsonify({
                        'error': _t('error.invalidField',
                                   '非法字段名')
                    }), 400

            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.extend([qrcode_id, org_id])
            c.execute(f'UPDATE qrcodes SET {", ".join(updates)} WHERE id=? AND org_id=?', params)
            conn.commit()

        if snapshot:
            save_version('qrcode', qrcode_id, json.dumps(snapshot, ensure_ascii=False),
                        remark=data.get('version_remark', '') or '')

        log_action('update_qrcode', 'qrcode', qrcode_id)
        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        logger.error(f"二维码更新失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>', methods=['DELETE'])
@login_required
def delete_qrcode(qrcode_id):
    """删除二维码（软删除→回收站）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT dynamic_link_id FROM qrcodes WHERE id=? AND org_id=? AND is_deleted=0', (qrcode_id, org_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404

            c.execute('''UPDATE qrcodes SET is_deleted=1, deleted_by=?, deleted_at=datetime('now'),
                         is_active=0, updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                     (session.get('user_id'), qrcode_id))
            if row['dynamic_link_id']:
                c.execute("UPDATE dynamic_links SET status='deleted', updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['dynamic_link_id'],))
            conn.commit()

        log_action('delete_qrcode', 'qrcode', qrcode_id)
        return jsonify({'success': True, 'message': '已移入回收站'})

    except Exception as e:
        logger.error(f"二维码删除失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/stats', methods=['GET'])
@login_required
def get_qrcode_stats(qrcode_id):
    """单个二维码扫码统计"""
    try:
        org_id = session.get('org_id')
        period = int(request.args.get('period', 7) or 7)
        if period not in (1, 7, 30):
            period = 7
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM qrcodes WHERE id=? AND org_id=?', (qrcode_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404
            
            scan_stats = _get_scan_stats(c, qrcode_id)
            today_scans = scan_stats['today']
            total_scans = scan_stats['total']

            c.execute(f"SELECT COUNT(*) FROM scan_logs WHERE qrcode_id=? AND scan_time >= datetime('now','-{period} days')", (qrcode_id,))
            period_scans = c.fetchone()[0]
            
            trend = []
            for i in range(period - 1, -1, -1):
                d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                c.execute("SELECT COUNT(*) FROM scan_logs WHERE qrcode_id=? AND date(scan_time)=?", (qrcode_id, d))
                trend.append({'date': d, 'count': c.fetchone()[0]})
            
            c.execute("SELECT device, COUNT(*) as cnt FROM scan_logs WHERE qrcode_id=? GROUP BY device", (qrcode_id,))
            device_stats = {r['device'] or 'unknown': r['cnt'] for r in c.fetchall()}
            
            c.execute("SELECT os, COUNT(*) as cnt FROM scan_logs WHERE qrcode_id=? GROUP BY os", (qrcode_id,))
            os_stats = {r['os'] or 'Other': r['cnt'] for r in c.fetchall()}
            
            c.execute("SELECT browser, COUNT(*) as cnt FROM scan_logs WHERE qrcode_id=? GROUP BY browser", (qrcode_id,))
            browser_stats = {r['browser'] or 'Other': r['cnt'] for r in c.fetchall()}
        
        return jsonify({
            'success': True,
            'summary': {'today': today_scans, 'period': period_scans, 'total': total_scans},
            'trend': trend,
            'device_stats': device_stats,
            'os_stats': os_stats,
            'browser_stats': browser_stats
        })
    
    except Exception as e:
        logger.error(f"扫码统计查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/tags', methods=['POST'])
@login_required
def set_qrcode_tags(qrcode_id):
    """给二维码设置标签"""
    try:
        data = request.get_json(silent=True) or {}
        org_id = session.get('org_id')
        tag_ids = data.get('tag_ids', [])
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM qrcodes WHERE id=? AND org_id=?', (qrcode_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404
            
            c.execute('DELETE FROM qrcode_tags WHERE qrcode_id=?', (qrcode_id,))
            for tid in tag_ids:
                c.execute('INSERT OR IGNORE INTO qrcode_tags (qrcode_id, tag_id) VALUES (?,?)', (qrcode_id, tid))
            conn.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        logger.error(f"标签设置失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.setFailed', '设置失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/tags', methods=['GET'])
@login_required
def get_qrcode_tags(qrcode_id):
    """查询二维码的标签"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM qrcodes WHERE id=? AND org_id=?', (qrcode_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404
            
            c.execute('''SELECT t.id, t.name, t.color FROM tags t
                        JOIN qrcode_tags qt ON t.id = qt.tag_id
                        WHERE qt.qrcode_id=? ORDER BY t.created_at DESC''', (qrcode_id,))
            tags = [{'id': r['id'], 'name': r['name'], 'color': r['color']} for r in c.fetchall()]
        
        return jsonify({'success': True, 'tags': tags})
    
    except Exception as e:
        logger.error(f"二维码标签查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/batch-export', methods=['POST'])
@login_required
def batch_export_qrcodes():
    """批量导出二维码"""
    try:
        data = request.get_json(silent=True) or {}
        qrcode_ids = data.get('ids', [])
        fmt = data.get('format', 'json')
        if not qrcode_ids:
            return jsonify({'error': _t('error.exportSelectRequired')}), 400
        
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            placeholders = ','.join('?' for _ in qrcode_ids)
            c.execute(f'SELECT * FROM qrcodes WHERE id IN ({placeholders}) AND org_id=?', qrcode_ids + [org_id])
            rows = c.fetchall()
        
        if fmt == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['ID', '标题', '分类', 'UUID', '状态', '扫码次数', '创建时间'])
            for r in rows:
                writer.writerow([r['id'], r['title'], r['category'], r['uuid_short'],
                                r['current_status'], r['scan_count'], r['created_at']])
            return jsonify({'success': True, 'csv': output.getvalue()})
        
        return jsonify({
            'success': True,
            'qrcodes': [dict(r) for r in rows]
        })
    except Exception as e:
        logger.error(f"批量导出失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.exportFailed')}), 500


@qr_management_bp.route('/api/qrcodes/lifecycle/list', methods=['GET'])
@require_permission('qrcode:view')
def lifecycle_list():
    """获取二维码生命周期列表（支持状态筛选）"""
    try:
        org_id = session.get('org_id')
        status_filter = request.args.get('status', '').strip()

        with get_db() as conn:
            c = conn.cursor()
            if status_filter:
                c.execute('''SELECT q.*, u.username as creator_name, ru.username as reviewer_name
                            FROM qrcodes q
                            LEFT JOIN users u ON q.creator_id = u.id
                            LEFT JOIN users ru ON q.review_user_id = ru.id
                            WHERE q.org_id = ? AND q.status = ? AND q.is_active = 1 AND q.is_deleted = 0
                            ORDER BY q.updated_at DESC LIMIT 100''', (org_id, status_filter))
            else:
                c.execute('''SELECT q.*, u.username as creator_name, ru.username as reviewer_name
                            FROM qrcodes q
                            LEFT JOIN users u ON q.creator_id = u.id
                            LEFT JOIN users ru ON q.review_user_id = ru.id
                            WHERE q.org_id = ? AND q.is_active = 1 AND q.is_deleted = 0
                            ORDER BY q.updated_at DESC LIMIT 100''', (org_id,))
            rows = c.fetchall()

        qrcodes = []
        for r in rows:
            qrcodes.append({
                'id': r['id'], 'uuid_short': r['uuid_short'],
                'title': r['title'], 'biz_type': r['biz_type'],
                'status': r['status'] or 'draft',
                'status_label': LIFECYCLE_LABELS.get(r['status'] or 'draft', '草稿'),
                'status_color': LIFECYCLE_COLORS.get(r['status'] or 'draft', '#94A3B8'),
                'scan_count': r['scan_count'],
                'created_at': r['created_at'],
                'published_at': r['published_at'],
                'expired_at': r['expired_at'],
                'archived_at': r['archived_at'],
                'deleted_at': r['deleted_at'],
                'creator_name': r['creator_name'],
                'reviewer_name': r['reviewer_name'],
                'review_comment': r['review_comment'],
                'available_transitions': LIFECYCLE_TRANSITIONS.get(r['status'] or 'draft', [])
            })

        return jsonify({
            'success': True,
            'qrcodes': qrcodes,
            'statuses': [{'key': k, 'label': v, 'color': LIFECYCLE_COLORS[k]} for k, v in LIFECYCLE_LABELS.items()]
        })
    except Exception as e:
        logger.error(f"生命周期列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/lifecycle/<int:qrcode_id>/timeline', methods=['GET'])
@require_permission('qrcode:view')
def lifecycle_timeline(qrcode_id):
    """获取单个二维码的生命周期时间轴"""
    try:
        org_id = session.get('org_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT q.*, u.username as creator_name, ru.username as reviewer_name
                        FROM qrcodes q
                        LEFT JOIN users u ON q.creator_id = u.id
                        LEFT JOIN users ru ON q.review_user_id = ru.id
                        WHERE q.id = ? AND q.org_id = ?''', (qrcode_id, org_id))
            qrcode = c.fetchone()

            if not qrcode:
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404

            c.execute('''SELECT * FROM audit_logs
                        WHERE target_type = 'qrcode' AND target_id = ?
                        AND action LIKE 'lifecycle_%'
                        ORDER BY created_at ASC''', (qrcode_id,))
            audit_rows = c.fetchall()

        qr = dict(qrcode)
        events = [{
            'stage': 'created',
            'label': '创建',
            'timestamp': qr['created_at'],
            'actor': qr['creator_name'] or '系统',
            'detail': f'创建二维码「{qr["title"]}」'
        }]

        for a in audit_rows:
            detail = json.loads(a['detail']) if a['detail'] else {}
            action = a['action']
            if action == 'lifecycle_review':
                events.append({
                    'stage': 'reviewing', 'label': '提交审核',
                    'timestamp': a['created_at'], 'actor': detail.get('username', '系统'),
                    'detail': detail.get('comment', '')
                })
            elif action == 'lifecycle_publish':
                events.append({
                    'stage': 'published', 'label': '发布',
                    'timestamp': qr['published_at'] or a['created_at'],
                    'actor': detail.get('username', '系统'),
                    'detail': ''
                })
            elif action == 'lifecycle_pause':
                events.append({
                    'stage': 'paused', 'label': '暂停',
                    'timestamp': a['created_at'], 'actor': detail.get('username', '系统'),
                    'detail': ''
                })
            elif action == 'lifecycle_resume':
                events.append({
                    'stage': 'running', 'label': '恢复运行',
                    'timestamp': a['created_at'], 'actor': detail.get('username', '系统'),
                    'detail': ''
                })
            elif action == 'lifecycle_expire':
                events.append({
                    'stage': 'expired', 'label': '失效',
                    'timestamp': qr['expired_at'] or a['created_at'],
                    'actor': detail.get('username', '系统'),
                    'detail': ''
                })
            elif action == 'lifecycle_archive':
                events.append({
                    'stage': 'archived', 'label': '归档',
                    'timestamp': qr['archived_at'] or a['created_at'],
                    'actor': detail.get('username', '系统'),
                    'detail': ''
                })
            elif action == 'lifecycle_delete':
                events.append({
                    'stage': 'deleted', 'label': '删除',
                    'timestamp': qr['deleted_at'] or a['created_at'],
                    'actor': detail.get('username', '系统'),
                    'detail': ''
                })

        current_status = qr['status'] or 'draft'
        return jsonify({
            'success': True,
            'qrcode': {
                'id': qr['id'], 'title': qr['title'], 'uuid_short': qr['uuid_short'],
                'status': current_status,
                'status_label': LIFECYCLE_LABELS.get(current_status, ''),
                'status_color': LIFECYCLE_COLORS.get(current_status, ''),
                'available_transitions': LIFECYCLE_TRANSITIONS.get(current_status, [])
            },
            'timeline': events
        })
    except Exception as e:
        logger.error(f"生命周期时间轴查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed')}), 500


@qr_management_bp.route('/api/qrcodes/lifecycle/transition', methods=['POST'])
@require_permission('qrcode:edit')
def lifecycle_transition():
    """执行状态流转"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': _t('error.requestBodyEmpty', '请求数据为空')}), 400

        qrcode_id = data.get('qrcode_id')
        target_status = data.get('target_status')
        comment = data.get('comment', '')

        if not qrcode_id or not target_status:
            return jsonify({'error': _t('error.missingRequiredParams', '缺少必要参数')}), 400

        org_id = session.get('org_id')
        user_id = session.get('user_id')
        username = session.get('username')

        with get_db() as conn:
            c = conn.cursor()
            qrcode = _get_qrcode_by_id_cursor(c, qrcode_id, org_id, check_deleted=False)

            if not qrcode:
                return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404

            current_status = qrcode['status'] or 'draft'
            valid, err_msg = validate_transition(current_status, target_status)
            if not valid:
                return jsonify({'error': err_msg}), 400

            now = datetime.now().isoformat()
            update_fields = ['status = ?', 'updated_at = ?']
            update_values = [target_status, now]

            action_map = {
                'reviewing': 'lifecycle_review',
                'published': 'lifecycle_publish',
                'running': 'lifecycle_resume',
                'paused': 'lifecycle_pause',
                'expired': 'lifecycle_expire',
                'archived': 'lifecycle_archive',
                'deleted': 'lifecycle_delete'
            }

            if target_status == 'published':
                update_fields.append('published_at = ?')
                update_values.append(now)
            elif target_status == 'expired':
                update_fields.append('expired_at = ?')
                update_values.append(now)
            elif target_status == 'archived':
                update_fields.append('archived_at = ?')
                update_values.append(now)
            elif target_status == 'deleted':
                update_fields.append('deleted_at = ?')
                update_values.append(now)
            elif target_status == 'reviewing':
                update_fields.append('review_user_id = ?')
                update_values.append(user_id)

            update_values.append(qrcode_id)
            c.execute(f'UPDATE qrcodes SET {", ".join(update_fields)} WHERE id = ?', update_values)
            conn.commit()

        save_version('qrcode', qrcode_id, json.dumps({
            'status': target_status
        }, ensure_ascii=False), remark=f'状态: {current_status} → {target_status}')

        log_action(
            action=action_map.get(target_status, f'lifecycle_{target_status}'),
            target_type='qrcode',
            target_id=qrcode_id,
            detail={'from_status': current_status, 'to_status': target_status,
                    'comment': comment, 'username': username}
        )

        return jsonify({
            'success': True,
            'message': f'状态已从 {LIFECYCLE_LABELS.get(current_status)} 切换为 {LIFECYCLE_LABELS.get(target_status)}',
            'new_status': target_status,
            'new_status_label': LIFECYCLE_LABELS.get(target_status, ''),
            'new_status_color': LIFECYCLE_COLORS.get(target_status, '')
        })
    except Exception as e:
        logger.error(f"状态流转失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.statusTransitionFailed', '状态流转失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/preview-data', methods=['GET'])
@login_required
def get_qrcode_preview_data(qrcode_id):
    """获取二维码预览数据"""
    try:
        org_id = session.get('org_id')
        qr = _get_qrcode_by_id(qrcode_id, org_id, check_deleted=True)
        if not qr:
            return jsonify({'error': _t('error.qrcodeNotFound', '二维码不存在')}), 404

        with get_db() as conn:
            c = conn.cursor()
            content_json = {}
            if qr['content_json']:
                try:
                    content_json = json.loads(qr['content_json'])
                except (json.JSONDecodeError, TypeError):
                    pass

            style_config = {}
            if qr['style_config']:
                try:
                    style_config = json.loads(qr['style_config'])
                except (json.JSONDecodeError, TypeError):
                    pass

            qr_url = None
            if qr['dynamic_link_id']:
                c.execute('SELECT short_code FROM dynamic_links WHERE id=?', (qr['dynamic_link_id'],))
                dl = c.fetchone()
                if dl:
                    qr_url = f"{Config.BASE_URL}/s/{dl['short_code']}"

        return jsonify({
            'success': True,
            'data': {
                'qr_code_id': qr['id'],
                'uuid_short': qr['uuid_short'],
                'title': qr['title'],
                'biz_type': qr['biz_type'],
                'content_json': content_json,
                'style_config': style_config,
                'current_status': qr['current_status'],
                'scan_count': qr['scan_count'],
                'is_active': qr['is_active'],
                'qr_url': qr_url,
                'created_at': str(qr['created_at']) if qr['created_at'] else None,
                'updated_at': str(qr['updated_at']) if qr['updated_at'] else None
            }
        })
    except Exception as e:
        logger.error(f"预览数据查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/preview-preferences', methods=['GET'])
@login_required
def get_preview_preferences(qrcode_id):
    """获取用户预览偏好"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT * FROM qr_preview_preferences WHERE org_id=? AND user_id=? AND qrcode_id=?',
                (org_id, user_id, qrcode_id)
            )
            row = c.fetchone()
            if row:
                prefs = dict(row)
                prefs.pop('id', None)
                prefs.pop('org_id', None)
                prefs.pop('user_id', None)
                prefs['created_at'] = str(prefs['created_at']) if prefs.get('created_at') else None
                prefs['updated_at'] = str(prefs['updated_at']) if prefs.get('updated_at') else None
            else:
                prefs = {
                    'last_device': 'iphone',
                    'theme': 'auto',
                    'orientation': 'portrait',
                    'zoom_level': 0.8,
                    'screenshot_format': 'png',
                    'screenshot_quality': 92,
                    'pdf_page_size': 'A4',
                    'pdf_orientation': 'portrait',
                    'pdf_include_meta': 1
                }
        return jsonify({'success': True, 'data': prefs})
    except Exception as e:
        logger.error(f"预览偏好查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


@qr_management_bp.route('/api/qrcodes/<int:qrcode_id>/preview-preferences', methods=['PUT'])
@login_required
def update_preview_preferences(qrcode_id):
    """更新用户预览偏好"""
    try:
        org_id = session.get('org_id')
        user_id = session.get('user_id')
        data = request.get_json(silent=True) or {}

        allowed_fields = [
            'last_device', 'theme', 'orientation', 'zoom_level',
            'screenshot_format', 'screenshot_quality',
            'pdf_page_size', 'pdf_orientation', 'pdf_include_meta'
        ]
        update_data = {k: data[k] for k in allowed_fields if k in data}
        if not update_data:
            return jsonify({'error': _t('error.noValidFields', '无有效字段')}), 400

        if 'zoom_level' in update_data:
            update_data['zoom_level'] = max(0.2, min(3.0, float(update_data['zoom_level'])))
        if 'screenshot_quality' in update_data:
            update_data['screenshot_quality'] = max(1, min(100, int(update_data['screenshot_quality'])))

        update_data['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id FROM qr_preview_preferences WHERE org_id=? AND user_id=? AND qrcode_id=?',
                (org_id, user_id, qrcode_id)
            )
            existing = c.fetchone()

            if existing:
                set_clause = ', '.join(f'{k}=?' for k in update_data)
                values = list(update_data.values()) + [org_id, user_id, qrcode_id]
                c.execute(
                    f'UPDATE qr_preview_preferences SET {set_clause} WHERE org_id=? AND user_id=? AND qrcode_id=?',
                    values
                )
            else:
                insert_data = {
                    'org_id': org_id,
                    'user_id': user_id,
                    'qrcode_id': qrcode_id,
                    'last_device': 'iphone',
                    'theme': 'auto',
                    'orientation': 'portrait',
                    'zoom_level': 0.8,
                    'screenshot_format': 'png',
                    'screenshot_quality': 92,
                    'pdf_page_size': 'A4',
                    'pdf_orientation': 'portrait',
                    'pdf_include_meta': 1,
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                insert_data.update(update_data)
                columns = ', '.join(insert_data)
                placeholders = ', '.join('?' for _ in insert_data)
                c.execute(
                    f'INSERT INTO qr_preview_preferences ({columns}) VALUES ({placeholders})',
                    list(insert_data.values())
                )
            conn.commit()

        log_action('preview_preferences_update', 'qrcode', qrcode_id,
                   detail={'updated_fields': list(update_data)})

        return jsonify({'success': True, 'data': {'updated': True}})
    except Exception as e:
        logger.error(f"预览偏好更新失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '更新失败')}), 500


@qr_management_bp.route('/api/preview/devices', methods=['GET'])
@login_required
def get_preview_devices():
    """获取可用设备列表"""
    devices = [
        {'key': 'iphone', 'name': 'iPhone 15 Pro', 'icon': '📱', 'category': 'phone', 'available': True},
        {'key': 'android', 'name': 'Android (Pixel 8)', 'icon': '🤖', 'category': 'phone', 'available': True},
        {'key': 'ipad', 'name': 'iPad Pro 12.9"', 'icon': '📋', 'category': 'tablet', 'available': True},
        {'key': 'pc', 'name': 'PC (1920×1080)', 'icon': '🖥', 'category': 'desktop', 'available': True},
        {'key': 'mac', 'name': 'MacBook Pro 16"', 'icon': '🍎', 'category': 'desktop', 'available': True},
        {'key': 'wechat', 'name': '微信内置浏览器', 'icon': '💬', 'category': 'inapp', 'available': True}
    ]
    return jsonify({'success': True, 'data': {'devices': devices}})