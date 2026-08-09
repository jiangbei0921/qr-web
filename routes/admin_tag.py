"""
admin_tag.py - 标签管理模块
提供标签的创建、列表查询和删除功能。

从 admin.py 拆分出来，独立管理标签相关路由。
"""
import re
import sqlite3

from flask import request, jsonify, session
from routes.shared import (
    get_db, login_required,
    _t, logger,
)


def register_tag_routes(bp):

    @bp.route('/api/tags', methods=['POST'])
    @login_required
    def create_tag():
        try:
            data = request.get_json(silent=True) or {}
            org_id = session.get('org_id')
            name = (data.get('name') or '').strip()
            color = (data.get('color') or '#1677FF').strip()

            if not name:
                return jsonify({'error': _t('error.tagNameRequired', '标签名称不能为空')}), 400

            if not re.match(r'^#[0-9A-Fa-f]{6}$', color):
                return jsonify({'error': _t('error.colorFormatError', '颜色格式错误，需为 #RRGGBB')}), 400

            with get_db() as conn:
                c = conn.cursor()
                try:
                    c.execute('INSERT INTO tags (org_id, name, color) VALUES (?,?,?)', (org_id, name, color))
                    tag_id = c.lastrowid
                    conn.commit()
                except sqlite3.IntegrityError:
                    return jsonify({'error': _t('error.tagNameExists', '标签名称已存在')}), 409

            return jsonify({'success': True, 'id': tag_id, 'name': name, 'color': color})

        except Exception as e:
            logger.error(f"标签创建失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.createFailed', '创建失败')}), 500

    @bp.route('/api/tags', methods=['GET'])
    @login_required
    def list_tags():
        try:
            org_id = session.get('org_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id, name, color, created_at FROM tags WHERE org_id=? ORDER BY created_at DESC', (org_id,))
                tags = [{'id': r['id'], 'name': r['name'], 'color': r['color']} for r in c.fetchall()]

            return jsonify({'success': True, 'tags': tags})

        except Exception as e:
            logger.error(f"标签列表查询失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500

    @bp.route('/api/tags/<int:tag_id>', methods=['DELETE'])
    @login_required
    def delete_tag(tag_id):
        try:
            org_id = session.get('org_id')
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT id FROM tags WHERE id=? AND org_id=?', (tag_id, org_id))
                if not c.fetchone():
                    return jsonify({'error': _t('error.tagNotFound')}), 404

                c.execute('DELETE FROM qrcode_tags WHERE tag_id=?', (tag_id,))
                c.execute('DELETE FROM tags WHERE id=?', (tag_id,))
                conn.commit()

            return jsonify({'success': True})

        except Exception as e:
            logger.error(f"标签删除失败: {e}", exc_info=True)
            return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500