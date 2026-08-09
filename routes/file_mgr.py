"""
file_mgr.py - 文件管理模块
负责上传、存储、管理用户上传的文件（图片、文档、PDF等）。

主要用于二维码Logo、表单附件、资产照片等场景。

主要功能：
1. 文件上传：支持多种文件类型，包含安全检查
2. 文件下载：提供预览和下载链接
3. 文件列表：分页查看，按类型筛选，支持搜索
4. 文件搜索：按文件名搜索
5. 文件详情：查看文件详细信息
6. 文件删除：软删除到回收站
7. 文件统计：统计各类型文件数量和总大小

安全措施：
- 文件扩展名白名单（只允许常见图片、文档、视频）
- 随机文件名生成，防止路径穿越攻击
- 使用 secure_filename 清理文件名
- 配额控制：限制存储容量
"""
import os
import uuid
import io
from flask import Blueprint, request, jsonify, session, send_from_directory
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, validate_file_extension,
    safe_filename, UPLOAD_FOLDER, check_quota, Config
)
from werkzeug.utils import secure_filename

file_bp = Blueprint('file_mgr', __name__)


@file_bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    """文件上传，含扩展名白名单校验和路径穿越防护"""
    try:
        file = request.files.get('file')
        if not file or not file.filename:
            return jsonify({'error': _t('error.noFileSelected')}), 400

        # 校验文件扩展名
        if not validate_file_extension(file.filename):
            return jsonify({'error': _t('error.unsupportedFileType')}), 400

        original_filename = file.filename
        ext = os.path.splitext(safe_filename(original_filename))[1].lower() or '.bin'
        fid = str(uuid.uuid4())[:12]
        fname = f'{fid}{ext}'
        file_path = os.path.join(UPLOAD_FOLDER, fname)

        org_id = session.get('org_id')
        passed, limit, used, msg = check_quota(org_id, 'max_storage_mb')
        if not passed:
            return jsonify({'error': msg, 'quota_key': 'max_storage_mb', 'limit': limit, 'used': used}), 403

        file.save(file_path)
        file_size = os.path.getsize(file_path)
        file_type_ext = ext.lstrip('.')
        user_id = session.get('user_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO files
                (org_id, name, original_name, path, file_type, size, created_by)
                VALUES (?,?,?,?,?,?,?)''',
                (org_id, fname, original_filename, file_path, file_type_ext, file_size, user_id))
            conn.commit()

        url = f'{Config.BASE_URL}/api/files/{fname}'
        return jsonify({'success': True, 'url': url})
    except Exception as e:
        logger.error(f"文件上传失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.uploadFailed')}), 500


@file_bp.route('/api/files/<fname>')
def api_serve_file(fname):
    """提供文件下载/预览，使用 secure_filename 防路径穿越"""
    safe_fname = secure_filename(fname)
    filepath = os.path.join(UPLOAD_FOLDER, safe_fname)
    if not os.path.exists(filepath):
        return jsonify({'error': _t('error.fileNotFound')}), 404
    ext = os.path.splitext(safe_fname)[1].lower()
    inline_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp4', '.mp3', '.wav', '.pdf'}
    as_attachment = ext not in inline_exts
    return send_from_directory(UPLOAD_FOLDER, safe_fname, as_attachment=as_attachment)


@file_bp.route('/api/files/list', methods=['GET'])
@login_required
def list_files():
    """文件列表"""
    try:
        org_id = session.get('org_id')
        page = int(request.args.get('page', 1) or 1)
        size = int(request.args.get('size', 20) or 20)
        file_type = (request.args.get('type') or '').strip()
        keyword = (request.args.get('keyword') or '').strip()
        
        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE org_id=? AND is_deleted=0'
            params = [org_id]
            
            if file_type:
                where += ' AND file_type=?'
                params.append(file_type)
            if keyword:
                where += ' AND (name LIKE ? OR original_name LIKE ?)'
                params.extend([f'%{keyword}%', f'%{keyword}%'])
            
            c.execute(f'SELECT COUNT(*) FROM files {where}', params)
            total = c.fetchone()[0]
            
            offset = (page - 1) * size
            c.execute(f'SELECT * FROM files {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
                     params + [size, offset])
            rows = c.fetchall()
        
        files_list = [{
            'id': r['id'], 'name': r['name'], 'original_name': r['original_name'],
            'file_type': r['file_type'], 'mime_type': r['mime_type'],
            'size': r['size'], 'version': r['version'], 'created_at': r['created_at'],
            'url': f"/api/files/{r['name']}"
        } for r in rows]
        
        return jsonify({'success': True, 'total': total, 'files': files_list})
    
    except Exception as e:
        logger.error(f"文件列表查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@file_bp.route('/api/files/search', methods=['GET'])
@login_required
def search_files():
    """文件搜索"""
    try:
        org_id = session.get('org_id')
        q = (request.args.get('q') or '').strip()
        if not q:
            return jsonify({'success': True, 'files': []})
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''SELECT * FROM files WHERE org_id=? AND is_deleted=0 AND (name LIKE ? OR original_name LIKE ?)
                        ORDER BY created_at DESC LIMIT 20''',
                     (org_id, f'%{q}%', f'%{q}%'))
            rows = c.fetchall()
        
        files_list = [{
            'id': r['id'], 'name': r['name'], 'original_name': r['original_name'],
            'file_type': r['file_type'], 'mime_type': r['mime_type'],
            'size': r['size'], 'version': r['version'], 'created_at': r['created_at'],
            'url': f"/api/files/{r['name']}"
        } for r in rows]
        
        return jsonify({'success': True, 'files': files_list})
    
    except Exception as e:
        logger.error(f"文件搜索失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.searchFailed', '搜索失败')}), 500



@file_bp.route('/api/files/<int:file_id>', methods=['GET'])
@login_required
def get_file_detail(file_id):
    """文件详情"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM files WHERE id=? AND org_id=?', (file_id, org_id))
            f = c.fetchone()
            if not f:
                return jsonify({'error': _t('error.fileNotFound', '文件不存在')}), 404
        
        return jsonify({
            'success': True,
            'file': {
                'id': f['id'], 'name': f['name'], 'original_name': f['original_name'],
                'file_type': f['file_type'], 'mime_type': f['mime_type'],
                'size': f['size'], 'version': f['version'], 'description': f['description'],
                'tags': f['tags'], 'created_at': f['created_at'], 'updated_at': f['updated_at'],
                'url': f"/api/files/{f['name']}"
            }
        })
    
    except Exception as e:
        logger.error(f"文件详情查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@file_bp.route('/api/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id):
    """文件删除（软删除→回收站）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT path FROM files WHERE id=? AND org_id=? AND is_deleted=0', (file_id, org_id))
            row = c.fetchone()
            if not row:
                return jsonify({'error': _t('error.fileNotFound')}), 404

            c.execute('''UPDATE files SET is_deleted=1, deleted_by=?, deleted_at=datetime('now')
                         WHERE id=? AND org_id=?''',
                     (session.get('user_id'), file_id, org_id))
            conn.commit()

        log_action('delete_file', 'file', file_id)
        return jsonify({'success': True, 'message': '已移入回收站'})

    except Exception as e:
        logger.error(f"文件删除失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500



@file_bp.route('/api/files/stats', methods=['GET'])
@login_required
def get_file_stats():
    """文件统计"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM files WHERE org_id=? AND is_deleted=0', (org_id,))
            total_files = c.fetchone()[0] or 0
            
            c.execute('SELECT COALESCE(SUM(size), 0) FROM files WHERE org_id=? AND is_deleted=0', (org_id,))
            total_size = c.fetchone()[0] or 0
            
            c.execute('SELECT file_type, COUNT(*) as cnt FROM files WHERE org_id=? AND is_deleted=0 GROUP BY file_type', (org_id,))
            by_type = {r['file_type'] or 'other': r['cnt'] for r in c.fetchall()}
        
        return jsonify({
            'success': True,
            'total_files': total_files,
            'total_size': total_size,
            'by_type': by_type
        })
    
    except Exception as e:
        logger.error(f"文件统计失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500


# ============ 批量二维码导出 API ============