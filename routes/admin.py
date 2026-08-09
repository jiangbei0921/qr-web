"""
admin.py - 管理后台模块
提供组织管理、用户管理、审计日志、批量操作等高级管理功能。

只有具有管理员权限的用户才能访问此模块中的大部分功能。
管理后台是整个系统的"控制中心"。

主要功能：
1. 组织统计：查看组织的基础数据统计
2. 模板管理：提供预置的二维码内容模板（文本/网址/名片/WiFi/邮件）
3. 用户管理：创建、编辑、停用、删除组织内的用户
4. 角色管理：分配用户角色和权限
5. 回收站：管理已删除的资源，支持恢复或永久删除
6. 批量操作：批量删除、导出、修改二维码
7. 审计日志：查看所有用户的操作记录
8. 批量任务：管理批量操作的后台任务

关键概念：
- 回收站（Recycle Bin）：软删除的资源先进入回收站，可恢复
- 批量操作（Batch）：支持同时处理大量数据，后台异步执行
- 审计日志（Audit Log）：记录谁在什么时间做了什么操作
"""
import json
import sqlite3
import threading

from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, check_quota,
    update_org_quota, generate_password_hash,
    ROLES, save_version, send_notification,
    parse_pagination,
    RECYCLE_RESOURCES,
    BATCH_RESOURCE_TABLES,
    BATCH_ACTIONS,
    ACTIVE_BATCH_TASKS,
    _batch_audit,
    _execute_batch_task,
    _rollback_batch_task,
)
from routes.admin_template import register_template_routes
from routes.admin_tag import register_tag_routes
from routes.admin_user import register_user_routes
from routes.admin_audit import register_audit_routes
from routes.admin_recycle import register_recycle_routes
from routes.admin_version import register_version_routes
from routes.admin_batch import register_batch_routes

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM qrcodes WHERE org_id = ? AND is_active = 1 AND is_deleted = 0', (org_id,))
            qrcode_count = c.fetchone()[0] or 0
            c.execute('SELECT COUNT(*) FROM users WHERE org_id = ?', (org_id,))
            user_count = c.fetchone()[0] or 0
        return jsonify({'success': True, 'total_qrcodes': qrcode_count, 'users': user_count})
    except Exception as e:
        logger.error(f"统计查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed')}), 500

register_template_routes(admin_bp)
register_tag_routes(admin_bp)
register_user_routes(admin_bp)
register_audit_routes(admin_bp)
register_recycle_routes(admin_bp)
register_version_routes(admin_bp)
register_batch_routes(admin_bp)