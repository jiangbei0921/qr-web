"""
department.py - 组织架构模块
管理企业组织架构（部门树、团队、职位、成员归属）。

在大型组织中，需要按部门层级划分权限和资产管理范围，
每个部门可以有多个子部门，每个用户可以分配到多个部门。

主要功能：
1. 组织树构建：返回完整的树形结构供前端显示
2. 节点创建：创建部门、团队等组织节点
3. 节点编辑：修改名称、负责人、描述等
4. 节点删除：软删除，防止误删
5. 成员管理：添加/移除部门成员
6. 权限分配：给部门分配功能权限
7. 批量导入：通过CSV文件批量导入组织架构

数据结构：
- path：存储路径信息，如 /1/5/ 表示根节点ID1→子节点ID5
- depth：存储节点深度，从0开始，方便层级查询
- 支持无限级嵌套，但实际使用建议控制在3-5级
"""
import csv
import hashlib
import hmac
import io
import json
import secrets
import sqlite3
import threading
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, request, jsonify,
    session, make_response, g
)
from routes.shared import (
    get_db,
    login_required,
    require_permission,
    log_action,
    _t,
    logger,
    PERMISSION_KEYS,
    _recalc_subtree,
    _sync_member_count,
    parse_pagination,
    _build_org_tree,
    NODE_TYPES
)

department_bp = Blueprint('department', __name__)


@department_bp.route('/api/org/tree', methods=['GET'])
@require_permission('qrcode:view')
def api_org_tree():
    """获取组织完整树结构（单次查询，应用层组装）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT * FROM departments WHERE org_id=? AND is_deleted=0 ORDER BY sort_order, id',
                (org_id,)
            )
            rows = c.fetchall()
        tree = _build_org_tree(rows)
        return jsonify({'success': True, 'data': {'tree': tree, 'total': len(rows)}})
    except Exception as e:
        logger.error(f"组织树查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@department_bp.route('/api/org/nodes', methods=['POST'])
@require_permission('user:manage')
def api_org_create_node():
    """创建组织节点"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': _t('error.nodeNameRequired', '节点名称不能为空')}), 400

        node_type = data.get('node_type', 'department')
        if node_type not in NODE_TYPES:
            return jsonify({'error': f'无效的节点类型, 可选: {", ".join(NODE_TYPES)}'}), 400

        parent_id = data.get('parent_id')
        leader_id = data.get('leader_id')
        leader_name = (data.get('leader_name') or '').strip()
        description = (data.get('description') or '').strip()
        sort_order = int(data.get('sort_order', 0))

        with get_db() as conn:
            c = conn.cursor()
            if parent_id:
                c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                          (parent_id, org_id))
                parent = c.fetchone()
                if not parent:
                    return jsonify({'error': _t('error.parentNodeNotFound', '父节点不存在')}), 404
                parent_path = parent['path']
                depth = parent['depth'] + 1
            else:
                parent_path = '/'
                depth = 0

            c.execute(
                'INSERT INTO departments (org_id, parent_id, name, node_type, path, depth, sort_order, leader_id, leader_name, description) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (org_id, parent_id, name, node_type, '', depth, sort_order, leader_id, leader_name, description)
            )
            dept_id = c.lastrowid
            path = f'{parent_path}{dept_id}/'
            c.execute('UPDATE departments SET path=? WHERE id=?', (path, dept_id))
            conn.commit()

        log_action('org_node_create', 'department', dept_id,
                   detail={'name': name, 'node_type': node_type, 'parent_id': parent_id})

        return jsonify({'success': True, 'data': {'id': dept_id, 'path': path, 'depth': depth}})
    except Exception as e:
        logger.error(f"创建节点失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.createFailed', '创建失败')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>', methods=['PUT'])
@require_permission('user:manage')
def api_org_edit_node(node_id):
    """编辑组织节点"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}

        allowed = ['name', 'node_type', 'leader_id', 'leader_name', 'description', 'sort_order']
        update_data = {}
        if 'name' in data:
            n = (data['name'] or '').strip()
            if not n:
                return jsonify({'error': _t('error.nodeNameRequired')}), 400
            update_data['name'] = n
        if 'node_type' in data and data['node_type'] in NODE_TYPES:
            update_data['node_type'] = data['node_type']
        if 'leader_id' in data:
            update_data['leader_id'] = data['leader_id']
        if 'leader_name' in data:
            update_data['leader_name'] = (data['leader_name'] or '').strip()
        if 'description' in data:
            update_data['description'] = (data['description'] or '').strip()
        if 'sort_order' in data:
            update_data['sort_order'] = int(data['sort_order'])

        if not update_data:
            return jsonify({'error': _t('error.noValidUpdateFields', '无有效更新字段')}), 400

        update_data['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.nodeNotFound', '节点不存在')}), 404

            set_clause = ', '.join(f'{k}=?' for k in update_data)
            c.execute(
                f'UPDATE departments SET {set_clause} WHERE id=? AND org_id=?',
                list(update_data.values()) + [node_id, org_id]
            )
            conn.commit()

        log_action('org_node_edit', 'department', node_id, detail=update_data)
        return jsonify({'success': True, 'data': update_data})
    except Exception as e:
        logger.error(f"编辑节点失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.updateFailed', '编辑失败')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>', methods=['DELETE'])
@require_permission('user:manage')
def api_org_delete_node(node_id):
    """软删除组织节点（校验子节点和成员）"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            node = c.fetchone()
            if not node:
                return jsonify({'error': _t('error.nodeNotFound', '节点不存在')}), 404

            c.execute('SELECT COUNT(*) FROM departments WHERE parent_id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            if c.fetchone()[0] > 0:
                return jsonify({'error': _t('error.nodeHasChildren', '该节点下存在子节点，请先删除或移动子节点')}), 400

            c.execute('SELECT COUNT(*) FROM department_users WHERE department_id=? AND org_id=?',
                      (node_id, org_id))
            if c.fetchone()[0] > 0:
                return jsonify({'error': _t('error.nodeHasMembers', '该节点下仍有成员归属，请先转移成员')}), 400

            c.execute('UPDATE departments SET is_deleted=1, updated_at=? WHERE id=? AND org_id=?',
                      (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), node_id, org_id))
            c.execute('DELETE FROM department_permissions WHERE department_id=? AND org_id=?',
                      (node_id, org_id))
            conn.commit()

        log_action('org_node_delete', 'department', node_id,
                   detail={'name': node['name'], 'node_type': node['node_type']})
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        logger.error(f"删除节点失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.deleteFailed', '删除失败')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>/move', methods=['PUT'])
@require_permission('user:manage')
def api_org_move_node(node_id):
    """移动单个节点到新父节点（含全子树路径重算，事务保护）"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        new_parent_id = data.get('parent_id')

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            node = c.fetchone()
            if not node:
                return jsonify({'error': _t('error.nodeNotFound')}), 404

            if new_parent_id is not None:
                c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                          (new_parent_id, org_id))
                new_parent = c.fetchone()
                if not new_parent:
                    return jsonify({'error': _t('error.targetParentNotFound')}), 404
                if new_parent['path'].startswith(node['path']):
                    return jsonify({'error': _t('error.cannotMoveToDescendant')}), 400
                new_parent_path = new_parent['path']
                new_depth = new_parent['depth'] + 1
            else:
                new_parent_path = '/'
                new_depth = 0
                new_parent_id = None

            _recalc_subtree(conn, node_id, org_id, new_parent_path, new_depth)
            c.execute('UPDATE departments SET parent_id=?, updated_at=? WHERE id=? AND org_id=?',
                      (new_parent_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), node_id, org_id))
            conn.commit()

        log_action('org_node_move', 'department', node_id,
                   detail={'name': node['name'], 'new_parent_id': new_parent_id})
        return jsonify({'success': True, 'message': '移动成功'})
    except Exception as e:
        logger.error(f"移动节点失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.moveFailed', '移动失败')}), 500



@department_bp.route('/api/org/nodes/batch-move', methods=['PUT'])
@require_permission('user:manage')
def api_org_batch_move_nodes():
    """批量移动多个节点到同一目标父节点"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        node_ids = data.get('node_ids', [])
        target_parent_id = data.get('parent_id')

        if not node_ids or not isinstance(node_ids, list):
            return jsonify({'error': _t('error.provideNodeIds')}), 400
        if len(node_ids) > 5000:
            return jsonify({'error': _t('error.batchMoveLimit')}), 400

        with get_db() as conn:
            c = conn.cursor()
            if target_parent_id is not None:
                c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                          (target_parent_id, org_id))
                target = c.fetchone()
                if not target:
                    return jsonify({'error': _t('error.targetParentNotFound', '目标父节点不存在')}), 404
                new_parent_path = target['path']
                new_depth = target['depth'] + 1
            else:
                new_parent_path = '/'
                new_depth = 0
                target_parent_id = None

            moved = 0
            for nid in node_ids:
                c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                          (nid, org_id))
                node = c.fetchone()
                if not node:
                    continue
                if target_parent_id is not None and new_parent_path.startswith(node['path']):
                    continue
                _recalc_subtree(conn, nid, org_id, new_parent_path, new_depth)
                c.execute('UPDATE departments SET parent_id=?, updated_at=? WHERE id=? AND org_id=?',
                          (target_parent_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), nid, org_id))
                moved += 1
            conn.commit()

        log_action('org_node_batch_move', 'department', 0,
                   detail={'count': moved, 'target_parent_id': target_parent_id})
        return jsonify({'success': True, 'moved': moved, 'message': f'成功移动{moved}个节点'})
    except Exception as e:
        logger.error(f"批量移动失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.moveFailed', '批量移动失败')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>/permissions', methods=['GET'])
@require_permission('qrcode:view')
def api_org_get_permissions(node_id):
    """获取某节点的有效权限（合并继承）和自身显式设置"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            node = c.fetchone()
            if not node:
                return jsonify({'error': _t('error.nodeNotFound', '节点不存在')}), 404

            c.execute('SELECT * FROM department_permissions WHERE department_id=? AND org_id=?',
                      (node_id, org_id))
            own_perms = {row['permission_key']: {
                'value': row['permission_value'],
                'inherit': bool(row['inherit_to_children'])
            } for row in c.fetchall()}

            path_parts = node['path'].strip('/').split('/')
            effective = {}
            for part in path_parts:
                if not part:
                    continue
                c.execute(
                    'SELECT * FROM department_permissions WHERE department_id=? AND org_id=?',
                    (int(part), org_id)
                )
                for row in c.fetchall():
                    effective[row['permission_key']] = {
                        'value': row['permission_value'],
                        'source': 'inherit' if int(part) != node_id else 'own',
                        'source_dept_id': int(part)
                    }

            for k, v in own_perms.items():
                effective[k] = {
                    'value': v['value'],
                    'source': 'own',
                    'source_dept_id': node_id,
                    'inherit_to_children': v['inherit']
                }

        return jsonify({'success': True, 'data': {
            'effective_permissions': effective,
            'own_permissions': own_perms,
            'permission_keys': PERMISSION_KEYS
        }})
    except Exception as e:
        logger.error(f"权限查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>/permissions', methods=['PUT'])
@require_permission('user:manage')
def api_org_set_permissions(node_id):
    """设置部门权限（支持批量）"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        permissions = data.get('permissions', {})

        if not isinstance(permissions, dict):
            return jsonify({'error': _t('error.permissionDataFormatError', '权限数据格式错误')}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.nodeNotFound', '节点不存在')}), 404

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for key, cfg in permissions.items():
                if key not in PERMISSION_KEYS:
                    continue
                value = cfg.get('value', 'deny')
                if value not in ('allow', 'deny'):
                    continue
                inherit = 1 if cfg.get('inherit_to_children', True) else 0
                c.execute(
                    'INSERT INTO department_permissions (org_id, department_id, permission_key, permission_value, inherit_to_children, updated_at) '
                    'VALUES (?,?,?,?,?,?) ON CONFLICT(department_id, permission_key) '
                    'DO UPDATE SET permission_value=?, inherit_to_children=?, updated_at=?',
                    (org_id, node_id, key, value, inherit, now, value, inherit, now)
                )
            conn.commit()

        log_action('org_permission_set', 'department', node_id,
                   detail={'permissions': {k: v.get('value') for k, v in permissions.items()}})
        return jsonify({'success': True, 'message': '权限设置成功'})
    except Exception as e:
        logger.error(f"权限设置失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.setFailed', '设置失败')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>/members', methods=['GET'])
@require_permission('qrcode:view')
def api_org_get_members(node_id):
    """获取部门成员列表"""
    try:
        org_id = session.get('org_id')
        page, size, offset = parse_pagination(default_size=50, max_size=200)
        keyword = (request.args.get('keyword') or '').strip()

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.nodeNotFound', '节点不存在')}), 404

            where = 'WHERE du.department_id=? AND du.org_id=?'
            params = [node_id, org_id]
            if keyword:
                where += ' AND u.username LIKE ?'
                params.append(f'%{keyword}%')

            c.execute(
                f'SELECT COUNT(*) FROM department_users du JOIN users u ON du.user_id=u.id {where}',
                params
            )
            total = c.fetchone()[0]

            c.execute(
                f'SELECT du.*, u.username, u.email, u.role_type FROM department_users du '
                f'JOIN users u ON du.user_id=u.id {where} '
                f'ORDER BY du.is_primary DESC, du.created_at DESC LIMIT ? OFFSET ?',
                params + [size, offset]
            )
            members = [dict(r) for r in c.fetchall()]

        return jsonify({
            'success': True, 'data': {
                'members': members, 'total': total,
                'page': page, 'size': size,
                'total_pages': max(1, (total + size - 1) // size)
            }
        })
    except Exception as e:
        logger.error(f"成员查询失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.queryFailed', '查询失败')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>/members', methods=['POST'])
@require_permission('user:manage')
def api_org_add_members(node_id):
    """给部门添加成员（批量，上限5000）"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        user_ids = data.get('user_ids', [])

        if not user_ids or not isinstance(user_ids, list):
            return jsonify({'error': _t('error.addUserIdsRequired', '请提供要添加的用户ID列表')}), 400
        if len(user_ids) > 5000:
            return jsonify({'error': _t('error.batchAddLimit', '单次批量添加上限5000条，请分批处理')}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                      (node_id, org_id))
            if not c.fetchone():
                return jsonify({'error': _t('error.nodeNotFound', '节点不存在')}), 404

            added = 0
            for uid in user_ids:
                try:
                    c.execute(
                        'INSERT INTO department_users (org_id, department_id, user_id, is_primary) VALUES (?,?,?,0)',
                        (org_id, node_id, uid)
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    pass
            _sync_member_count(conn, node_id, org_id)
            conn.commit()

        log_action('org_member_add', 'department', node_id,
                   detail={'added': added, 'user_ids': user_ids})
        return jsonify({'success': True, 'added': added, 'message': f'成功添加{added}名成员'})
    except Exception as e:
        logger.error(f"添加成员失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.addFailed')}), 500



@department_bp.route('/api/org/nodes/<int:node_id>/members', methods=['DELETE'])
@require_permission('user:manage')
def api_org_remove_members(node_id):
    """从部门移除成员（批量）"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        user_ids = data.get('user_ids', [])

        if not user_ids or not isinstance(user_ids, list):
            return jsonify({'error': _t('error.removeUserIdsRequired', '请提供要移除的用户ID列表')}), 400

        with get_db() as conn:
            c = conn.cursor()
            placeholders = ','.join('?' for _ in user_ids)
            c.execute(
                f'DELETE FROM department_users WHERE department_id=? AND org_id=? AND user_id IN ({placeholders})',
                [node_id, org_id] + user_ids
            )
            removed = c.rowcount
            _sync_member_count(conn, node_id, org_id)
            conn.commit()

        log_action('org_member_remove', 'department', node_id,
                   detail={'removed': removed, 'user_ids': user_ids})
        return jsonify({'success': True, 'removed': removed, 'message': f'成功移除{removed}名成员'})
    except Exception as e:
        logger.error(f"移除成员失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.removeFailed', '移除失败')}), 500



@department_bp.route('/api/org/members/transfer', methods=['POST'])
@require_permission('user:manage')
def api_org_transfer_members():
    """批量转移成员从一个部门到另一个部门"""
    try:
        org_id = session.get('org_id')
        data = request.get_json(silent=True) or {}
        user_ids = data.get('user_ids', [])
        from_dept_id = data.get('from_dept_id')
        to_dept_id = data.get('to_dept_id')

        if not user_ids or not isinstance(user_ids, list):
            return jsonify({'error': _t('error.transferUserIdsRequired', '请提供要转移的用户ID列表')}), 400
        if len(user_ids) > 5000:
            return jsonify({'error': _t('error.transferLimit', '单次转移上限5000条，请分批处理')}), 400
        if not from_dept_id or not to_dept_id:
            return jsonify({'error': _t('error.transferDeptRequired', '请提供来源和目标部门ID')}), 400
        if from_dept_id == to_dept_id:
            return jsonify({'error': _t('error.transferSameDept', '来源和目标部门不能相同')}), 400

        with get_db() as conn:
            c = conn.cursor()
            for dept_id in [from_dept_id, to_dept_id]:
                c.execute('SELECT * FROM departments WHERE id=? AND org_id=? AND is_deleted=0',
                          (dept_id, org_id))
                if not c.fetchone():
                    return jsonify({'error': f'部门ID={dept_id}不存在'}), 404

            placeholders = ','.join('?' for _ in user_ids)
            c.execute(
                f'DELETE FROM department_users WHERE department_id=? AND org_id=? AND user_id IN ({placeholders})',
                [from_dept_id, org_id] + user_ids
            )
            removed = c.rowcount

            added = 0
            for uid in user_ids:
                try:
                    c.execute(
                        'INSERT INTO department_users (org_id, department_id, user_id, is_primary) VALUES (?,?,?,0)',
                        (org_id, to_dept_id, uid)
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    pass

            _sync_member_count(conn, from_dept_id, org_id)
            _sync_member_count(conn, to_dept_id, org_id)
            conn.commit()

        log_action('org_member_transfer', 'department', to_dept_id,
                   detail={'from_dept_id': from_dept_id, 'removed': removed, 'added': added})
        return jsonify({'success': True, 'removed': removed, 'added': added,
                       'message': f'转移完成: {removed}人迁出, {added}人迁入'})
    except Exception as e:
        logger.error(f"成员转移失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.transferFailed')}), 500



@department_bp.route('/api/org/users/search', methods=['GET'])
@require_permission('qrcode:view')
def api_org_search_users():
    """搜索用户（用于添加成员选择器）"""
    try:
        org_id = session.get('org_id')
        keyword = (request.args.get('keyword') or '').strip()
        page, size, offset = parse_pagination(default_size=20, max_size=100)

        with get_db() as conn:
            c = conn.cursor()
            where = 'WHERE org_id=?'
            params = [org_id]
            if keyword:
                where += ' AND (username LIKE ? OR email LIKE ?)'
                params.extend([f'%{keyword}%', f'%{keyword}%'])

            c.execute(f'SELECT COUNT(*) FROM users {where}', params)
            total = c.fetchone()[0]

            c.execute(
                f'SELECT id, username, email, role_type FROM users {where} ORDER BY id LIMIT ? OFFSET ?',
                params + [size, offset]
            )
            users = [dict(r) for r in c.fetchall()]

        return jsonify({'success': True, 'data': {'users': users, 'total': total}})
    except Exception as e:
        logger.error(f"用户搜索失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.searchFailed', '搜索失败')}), 500



@department_bp.route('/api/org/node-types', methods=['GET'])
@require_permission('qrcode:view')
def api_org_node_types():
    """获取可用节点类型列表"""
    types = [{'key': k, 'label': v} for k, v in NODE_TYPES.items()]
    return jsonify({'success': True, 'data': {'types': types}})



@department_bp.route('/api/org/export', methods=['GET'])
@require_permission('qrcode:view')
def api_org_export():
    """导出组织架构为CSV"""
    try:
        org_id = session.get('org_id')
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT d.*, p.name as parent_name FROM departments d '
                'LEFT JOIN departments p ON d.parent_id=p.id '
                'WHERE d.org_id=? AND d.is_deleted=0 ORDER BY d.path',
                (org_id,)
            )
            rows = c.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', '名称', '节点类型', '父节点名称', '层级', '负责人', '成员数', '描述', '路径'])
        for r in rows:
            writer.writerow([
                r['id'], r['name'], NODE_TYPES.get(r['node_type'], r['node_type']),
                r['parent_name'] or '', r['depth'], r['leader_name'] or '',
                r['member_count'], r['description'] or '', r['path']
            ])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        response.headers['Content-Disposition'] = 'attachment; filename=organization.csv'
        return response
    except Exception as e:
        logger.error(f"导出失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.exportFailed', '导出失败')}), 500



@department_bp.route('/api/org/import', methods=['POST'])
@require_permission('user:manage')
def api_org_import():
    """通过CSV批量导入组织架构"""
    try:
        org_id = session.get('org_id')
        file = request.files.get('file')
        if not file:
            return jsonify({'error': _t('error.uploadCsv')}), 400

        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))

        required_fields = ['name']
        for field in required_fields:
            if field not in (reader.fieldnames or []):
                return jsonify({'error': f'CSV缺少必填字段: {field}'}), 400

        errors = []
        created = 0
        line_num = 1

        with get_db() as conn:
            c = conn.cursor()
            id_map = {}

            for row in reader:
                line_num += 1
                name = (row.get('name') or '').strip()
                if not name:
                    errors.append(f'第{line_num}行: 名称为空')
                    continue

                node_type = (row.get('node_type') or 'department').strip()
                if node_type not in NODE_TYPES:
                    node_type = 'department'

                parent_name = (row.get('parent_name') or '').strip()
                parent_id = None
                parent_path = '/'
                depth = 0

                if parent_name:
                    c.execute('SELECT id, path, depth FROM departments WHERE org_id=? AND name=? AND is_deleted=0',
                              (org_id, parent_name))
                    parent = c.fetchone()
                    if parent:
                        parent_id = parent['id']
                        parent_path = parent['path']
                        depth = parent['depth'] + 1
                    else:
                        errors.append(f'第{line_num}行: 父节点"{parent_name}"不存在，跳过')
                        continue

                description = (row.get('description') or '').strip()
                leader_name = (row.get('leader_name') or '').strip()
                sort_order = int(row.get('sort_order', 0) or 0)

                c.execute(
                    'INSERT INTO departments (org_id, parent_id, name, node_type, path, depth, sort_order, leader_name, description) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (org_id, parent_id, name, node_type, '', depth, sort_order, leader_name, description)
                )
                dept_id = c.lastrowid
                path = f'{parent_path}{dept_id}/'
                c.execute('UPDATE departments SET path=? WHERE id=?', (path, dept_id))
                id_map[name] = dept_id
                created += 1

            conn.commit()

        log_action('org_import', 'department', 0,
                   detail={'created': created, 'errors': len(errors), 'total_lines': line_num - 1})

        result = {'success': True, 'created': created, 'errors': errors,
                  'message': f'成功创建{created}个节点'}
        if errors:
            result['message'] += f'，{len(errors)}行错误'
        return jsonify(result)
    except Exception as e:
        logger.error(f"导入失败: {e}", exc_info=True)
        return jsonify({'error': _t('error.importFailed', '导入失败')}), 500


# ============================================
# 开放API平台
# ============================================

# ── 内存限流器 ──
_rate_limit_store = {}
_rate_limit_lock = threading.Lock()

def _openapi_rate_limit(app_id, rate_limit_qpm):
    """滑动窗口限流检查，返回 (通过, 重试秒数)"""
    now = int(datetime.now().timestamp())
    key = f'rl:{app_id}'
    with _rate_limit_lock:
        if key not in _rate_limit_store:
            _rate_limit_store[key] = []
        window = [t for t in _rate_limit_store[key] if t > now - 60]
        if len(window) >= rate_limit_qpm:
            retry_after = 60 - (now - window[0])
            return False, max(1, retry_after)
        window.append(now)
        _rate_limit_store[key] = window
        return True, 0


# ── 辅助函数 ──
def _openapi_generate_app_key():
    """生成32位随机应用公钥"""
    return 'ak_' + secrets.token_hex(14)

def _openapi_generate_secret():
    """生成48位随机应用密钥"""
    return 'sk_' + secrets.token_hex(22)

def _openapi_verify_signature(app_secret, method, path, body, timestamp, signature):
    """验证HMAC-SHA256请求签名"""
    sign_str = f'{method.upper()}|{path}|{body}|{timestamp}'
    expected = hmac.new(app_secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def _openapi_generate_jwt(app_id, user_id, org_id, app_secret, expire_minutes=60):
    """签发JWT令牌"""
    import base64 as b64
    now = int(datetime.now().timestamp())
    header = b64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode()).rstrip(b'=').decode()
    payload = b64.urlsafe_b64encode(json.dumps({
        'app_id': app_id, 'user_id': user_id, 'org_id': org_id,
        'iat': now, 'exp': now + expire_minutes * 60,
        'jti': secrets.token_hex(12)
    }).encode()).rstrip(b'=').decode()
    signature = hmac.new(app_secret.encode('utf-8'), f'{header}.{payload}'.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{header}.{payload}.{signature}'

def _openapi_verify_jwt(token, app_secret):
    """验证JWT令牌，返回负载或None"""
    import base64 as b64
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload, signature = parts
        expected = hmac.new(app_secret.encode('utf-8'), f'{header}.{payload}'.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        data = json.loads(b64.urlsafe_b64decode(payload))
        if data.get('exp', 0) < int(datetime.now().timestamp()):
            return None
        return data
    except Exception:
        return None

def _openapi_log_access(app_id, org_id, user_id, status_code, error_message='', request_time=0):
    """记录开放API访问日志"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO openapi_access_logs (app_id, org_id, user_id, method, path, query_params, status_code, error_message, request_ip, request_time) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (app_id, org_id, user_id, request.method, request.path,
                 json.dumps(dict(request.args), ensure_ascii=False) if request.args else '',
                 status_code, error_message, request.remote_addr, request_time)
            )
            conn.commit()
    except Exception:
        pass

def _openapi_authenticate():
    """统一开放API认证中间件，返回 (org_id, user_id, app_id, auth_type) 或 (None, error_msg, status_code)"""

    auth_header = request.headers.get('Authorization', '')
    if not auth_header:
        return None, '缺少Authorization请求头', 401

    # ── 方式1: API Key + HMAC 签名 ──
    if auth_header.startswith('Apikey '):
        parts = auth_header[7:].strip().split(':')
        if len(parts) != 2:
            return None, 'Apikey格式错误: 应为 Apikey {app_key}:{signature}', 401
        app_key, signature = parts

        timestamp = request.headers.get('X-Timestamp', '')
        if not timestamp:
            return None, '缺少X-Timestamp请求头', 401
        try:
            ts = int(timestamp)
            now = int(datetime.now().timestamp())
            if abs(now - ts) > 300:
                return None, '请求时间戳超出允许范围（±5分钟）', 401
        except ValueError:
            return None, 'X-Timestamp格式无效', 401

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM openapps WHERE app_key=? AND is_enabled=1', (app_key,))
            app = c.fetchone()
            if not app:
                return None, '应用不存在或已被禁用', 403

            # IP白名单检查
            ip_whitelist = (app['ip_whitelist'] or '').strip()
            if ip_whitelist:
                allowed_ips = [ip.strip() for ip in ip_whitelist.split('\n') if ip.strip()]
                if allowed_ips and request.remote_addr not in allowed_ips:
                    _openapi_log_access(app['id'], app['org_id'], app['created_by'], 403, f'IP白名单拒绝: {request.remote_addr}')
                    return None, 'IP地址不在白名单范围内', 403

            # 限流检查
            rate_limit_qpm = app['rate_limit_qpm'] or 100
            passed, retry_after = _openapi_rate_limit(app['id'], rate_limit_qpm)
            if not passed:
                _openapi_log_access(app['id'], app['org_id'], app['created_by'], 429, f'限流: {rate_limit_qpm}qpm')
                return None, f'请求频率超限（{rate_limit_qpm}次/分钟），请{retry_after}秒后重试', 429

            # 签名校验
            body = request.get_data(as_text=True) or ''
            if not _openapi_verify_signature(app['app_secret'], request.method, request.path, body, timestamp, signature):
                _openapi_log_access(app['id'], app['org_id'], app['created_by'], 401, '签名校验失败')
                return None, '签名校验失败', 401

            return app['org_id'], app['created_by'], app['id'], 'apikey'

    # ── 方式2: JWT Token ──
    elif auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
        import base64 as b64
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None, 'JWT格式无效', 401
            payload_enc = parts[1]
            padding = 4 - len(payload_enc) % 4
            if padding != 4:
                payload_enc += '=' * padding
            payload_data = json.loads(b64.urlsafe_b64decode(payload_enc))
            app_id = payload_data.get('app_id')
            jti = payload_data.get('jti')
            if not app_id:
                return None, 'JWT缺少app_id', 401

            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM openapps WHERE id=? AND is_enabled=1', (app_id,))
                app = c.fetchone()
                if not app:
                    return None, '应用不存在或已被禁用', 403

                # 检查JTI是否被吊销
                if jti:
                    c.execute('SELECT * FROM openapps_tokens WHERE jti=? AND revoked=1', (jti,))
                    if c.fetchone():
                        return None, '令牌已被吊销', 401

                # 验证签名
                data = _openapi_verify_jwt(token, app['app_secret'])
                if not data:
                    _openapi_log_access(app['id'], app['org_id'], None, 401, 'JWT验证失败')
                    return None, 'JWT令牌无效或已过期', 401

                # IP白名单
                ip_whitelist = (app['ip_whitelist'] or '').strip()
                if ip_whitelist:
                    allowed_ips = [ip.strip() for ip in ip_whitelist.split('\n') if ip.strip()]
                    if allowed_ips and request.remote_addr not in allowed_ips:
                        _openapi_log_access(app['id'], app['org_id'], data.get('user_id'), 403, f'IP白名单拒绝: {request.remote_addr}')
                        return None, 'IP地址不在白名单范围内', 403

                # 限流
                rate_limit_qpm = app['rate_limit_qpm'] or 100
                passed, retry_after = _openapi_rate_limit(app['id'], rate_limit_qpm)
                if not passed:
                    _openapi_log_access(app['id'], app['org_id'], data.get('user_id'), 429, f'限流: {rate_limit_qpm}qpm')
                    return None, f'请求频率超限（{rate_limit_qpm}次/分钟），请{retry_after}秒后重试', 429

                return data.get('org_id'), data.get('user_id'), app['id'], 'jwt'
        except Exception:
            return None, 'JWT解析失败', 401

    # ── 方式3: OAuth2 Access Token ──
    elif auth_header.startswith('OAuth '):
        access_token = auth_header[6:].strip()
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT ot.*, oc.org_id, oc.is_enabled as client_enabled FROM oauth2_tokens ot '
                'JOIN oauth2_clients oc ON ot.client_id=oc.id '
                'WHERE ot.access_token=? AND ot.expires_at > ?',
                (access_token, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            token_row = c.fetchone()
            if not token_row or not token_row['client_enabled']:
                return None, 'OAuth令牌无效或已过期', 401

            return token_row['org_id'], token_row['user_id'], None, 'oauth2'

    return None, '不支持的认证方式', 401


def openapi_auth(f):
    """开放API认证装饰器，自动识别认证方式并注入上下文"""
    @wraps(f)
    def decorated(*args, **kwargs):
        start_time = int(datetime.now().timestamp())
        org_id, user_id_or_error, app_id, status_or_401 = None, None, None, 200

        result = _openapi_authenticate()
        if len(result) == 3 and result[0] is None:
            error_msg, status_code = result[1], result[2]
            return jsonify({'error': error_msg, 'code': status_code}), status_code

        org_id, user_id, app_id, auth_type = result
        g.org_id = org_id
        g.user_id = user_id
        g.app_id = app_id
        g.auth_type = auth_type

        try:
            response = f(*args, **kwargs)
            elapsed = int((datetime.now().timestamp() - start_time) * 1000)
            if isinstance(response, tuple):
                resp, status = response
                _openapi_log_access(app_id, org_id, user_id, status, '', elapsed)
                return resp, status
            _openapi_log_access(app_id, org_id, user_id, 200, '', elapsed)
            return response
        except Exception as e:
            elapsed = int((datetime.now().timestamp() - start_time) * 1000)
            _openapi_log_access(app_id, org_id, user_id, 500, str(e), elapsed)
            raise
    return decorated


# ── 开放API路由（v1） ──

def _openapi_paginate():
    """从请求参数提取分页信息"""
    page = max(1, int(request.args.get('page', 1)))
    size = min(200, max(1, int(request.args.get('size', 50))))
    return page, size

def _openapi_row_to_dict(row):
    """将sqlite3.Row转为字典"""
    return dict(row) if row else None