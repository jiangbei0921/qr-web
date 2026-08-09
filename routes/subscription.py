"""
subscription.py - 订阅与计费模块
负责管理组织的订阅套餐、支付和配额。

订阅系统控制每个组织可以使用的功能范围和资源上限。
不同套餐提供不同的功能权限和资源配额。

主要功能：
1. 套餐列表：查看所有可用的订阅套餐
2. 我的订阅：查看当前组织的订阅状态
3. 订阅套餐：选择并订阅套餐
4. 支付确认：确认支付完成
5. 取消订阅：取消当前订阅
6. 自动续费：切换自动续费开关
7. 账单历史：查看历史账单记录
8. 配额使用：查看各项资源的使用情况
9. 收入统计：运营方查看收入数据

套餐类型：
- free：免费套餐（基础功能，有限配额）
- starter：入门套餐（适合小型团队）
- professional：专业套餐（适合中型企业）
- enterprise：企业套餐（适合大型组织，无限制）
"""
import json

from flask import Blueprint, request, jsonify, session
from routes.shared import (
    get_db, login_required, require_permission,
    _t, log_action, logger, get_org_quota, get_org_subscription
)
from routes.workflow import sync_quota_usage, PaymentGateway

subscription_bp = Blueprint('subscription', __name__)


@subscription_bp.route('/api/subscription/plans', methods=['GET'])
def api_subscription_plans():
    """获取所有套餐列表"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM plan_tiers WHERE is_enabled=1 ORDER BY sort_order')
        plans = []
        for row in c.fetchall():
            plans.append({
                'id': row['id'], 'plan_key': row['plan_key'], 'name': row['name'],
                'description': row['description'], 'monthly_price': row['monthly_price'],
                'yearly_price': row['yearly_price'],
                'features': json.loads(row['features_json'] or '{}'),
                'quotas': json.loads(row['quotas_json'] or '{}')
            })
    return jsonify({'success': True, 'plans': plans})



@subscription_bp.route('/api/subscription/my', methods=['GET'])
@login_required
def api_subscription_my():
    """获取当前组织的订阅信息"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    sub = get_org_subscription(org_id)
    if not sub:
        return jsonify({'success': True, 'subscription': None})
    return jsonify({'success': True, 'subscription': {
        'id': sub['id'], 'plan_key': sub['plan_key'], 'plan_name': sub['plan_name'],
        'status': sub['status'], 'start_date': sub['start_date'], 'end_date': sub['end_date'],
        'auto_renew': sub['auto_renew'], 'monthly_price': sub['monthly_price'],
        'yearly_price': sub['yearly_price'],
        'features': json.loads(sub['features_json'] or '{}'),
        'quotas': json.loads(sub['quotas_json'] or '{}'),
        'plan_desc': sub['plan_desc']
    }})



@subscription_bp.route('/api/subscription/subscribe', methods=['POST'])
@login_required
def api_subscription_subscribe():
    """订阅/升级套餐"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    data = request.get_json(silent=True) or {}
    plan_key = data.get('plan_key')
    billing_cycle = data.get('billing_cycle', 'monthly')

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM plan_tiers WHERE plan_key=? AND is_enabled=1', (plan_key,))
        plan = c.fetchone()
        if not plan:
            return jsonify({'error': _t('error.subscriptionPlanNotFound', '套餐不存在')}), 404

        amount = plan['yearly_price'] if billing_cycle == 'yearly' else plan['monthly_price']
        sub = get_org_subscription(org_id)

        if amount == 0:
            c.execute('''UPDATE subscriptions SET plan_id=?, status=?, start_date=CURRENT_TIMESTAMP,
                        end_date=datetime('now','+30 days'), updated_at=CURRENT_TIMESTAMP
                        WHERE org_id=?''', (plan['id'], 'active', org_id))
            if not c.rowcount:
                c.execute('''INSERT INTO subscriptions (org_id, plan_id, status, start_date, end_date)
                            VALUES (?,?,?,CURRENT_TIMESTAMP,datetime('now','+30 days'))''',
                         (org_id, plan['id'], 'active'))
            c.execute('''INSERT INTO billing_invoices (org_id, plan_id, amount, currency, status, invoice_type, paid_at,
                        billing_period_start, billing_period_end)
                        VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP,datetime('now'),datetime('now','+30 days'))''',
                     (org_id, plan['id'], 0, 'CNY', 'paid', 'new_subscription'))
            conn.commit()
            return jsonify({'success': True, 'message': '已切换到' + plan['name']})

        pay_url, txn_id, invoice_id = PaymentGateway.create_order(org_id, plan['id'], amount)
        conn.commit()
        return jsonify({'success': True, 'pay_url': pay_url, 'txn_id': txn_id, 'invoice_id': invoice_id})



@subscription_bp.route('/api/subscription/confirm-payment', methods=['POST'])
@login_required
def api_subscription_confirm_payment():
    """确认支付（模拟自动完成）"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    data = request.get_json(silent=True) or {}
    txn_id = data.get('txn_id')
    if not txn_id:
        return jsonify({'error': _t('error.transactionIdRequired', '缺少交易ID')}), 400

    success, inv = PaymentGateway.confirm_payment(txn_id)
    if not success or isinstance(inv, str):
        return jsonify({'error': inv}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE subscriptions SET plan_id=?, status=?, last_payment_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE org_id=?',
                 (inv['plan_id'], 'active', org_id))
        if not c.rowcount:
            c.execute('''INSERT INTO subscriptions (org_id, plan_id, status, start_date, last_payment_at)
                        VALUES (?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)''',
                     (org_id, inv['plan_id'], 'active'))
        c.execute('UPDATE billing_invoices SET subscription_id=(SELECT id FROM subscriptions WHERE org_id=? ORDER BY id DESC LIMIT 1) WHERE id=?',
                 (org_id, inv['id']))
        conn.commit()
    log_action('subscription_paid', 'subscription', org_id, {'plan_id': inv['plan_id'], 'amount': inv['amount']})
    return jsonify({'success': True, 'message': '支付成功，订阅已生效'})



@subscription_bp.route('/api/subscription/cancel', methods=['POST'])
@login_required
def api_subscription_cancel():
    """取消订阅"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', '')
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''UPDATE subscriptions SET status=?, auto_renew=0, cancelled_at=CURRENT_TIMESTAMP,
                    cancel_reason=?, updated_at=CURRENT_TIMESTAMP WHERE org_id=?''',
                 ('cancelled', reason, org_id))
        conn.commit()
    log_action('subscription_cancelled', 'subscription', org_id, {'reason': reason})
    return jsonify({'success': True, 'message': '订阅已取消'})



@subscription_bp.route('/api/subscription/auto-renew', methods=['POST'])
@login_required
def api_subscription_auto_renew():
    """切换自动续费"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    data = request.get_json(silent=True) or {}
    auto_renew = 1 if data.get('auto_renew') else 0
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE subscriptions SET auto_renew=?, updated_at=CURRENT_TIMESTAMP WHERE org_id=?', (auto_renew, org_id))
        conn.commit()
    return jsonify({'success': True, 'auto_renew': auto_renew})



@subscription_bp.route('/api/subscription/billing-history', methods=['GET'])
@login_required
def api_subscription_billing_history():
    """获取账单历史"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''SELECT bi.*, pt.name as plan_name FROM billing_invoices bi
                    LEFT JOIN plan_tiers pt ON bi.plan_id=pt.id
                    WHERE bi.org_id=? ORDER BY bi.created_at DESC LIMIT 50''', (org_id,))
        rows = c.fetchall()
    return jsonify({'success': True, 'invoices': [dict(r) for r in rows]})



@subscription_bp.route('/api/subscription/quota-usage', methods=['GET'])
@login_required
def api_subscription_quota_usage():
    """获取配额使用情况"""
    org_id = session.get('org_id')
    if not org_id:
        return jsonify({'error': _t('auth.sessionExpired', '未登录')}), 401
    sub = get_org_subscription(org_id)
    if not sub:
        return jsonify({'success': True, 'quotas': {}})
    sync_quota_usage(org_id)
    quotas = json.loads(sub['quotas_json'] or '{}')
    usage = {}
    for k, v in quotas.items():
        usage[k] = {'limit': v, 'used': get_org_quota(org_id, k)}
    return jsonify({'success': True, 'plan_key': sub['plan_key'], 'plan_name': sub['plan_name'], 'quotas': usage})


# ── 运营收入统计 API ──


@subscription_bp.route('/api/admin/revenue/summary', methods=['GET'])
@require_permission('user:manage')
def api_admin_revenue_summary():
    """收入统计面板"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as total FROM billing_invoices WHERE status=?', ('paid',))
        total_paid = c.fetchone()['total']
        c.execute('SELECT COALESCE(SUM(amount),0) as total FROM billing_invoices WHERE status=?', ('paid',))
        total_revenue = c.fetchone()['total']
        c.execute('''SELECT COALESCE(SUM(amount),0) as total FROM billing_invoices
                    WHERE status=? AND created_at >= datetime('now','-30 days')''', ('paid',))
        revenue_30d = c.fetchone()['total']

        c.execute('''SELECT pt.plan_key, pt.name, COUNT(*) as cnt, COALESCE(SUM(bi.amount),0) as revenue
                    FROM billing_invoices bi
                    JOIN plan_tiers pt ON bi.plan_id=pt.id
                    WHERE bi.status='paid'
                    GROUP BY pt.id ORDER BY pt.sort_order''')
        by_plan = [dict(r) for r in c.fetchall()]

        c.execute('''SELECT COUNT(*) as cnt FROM subscriptions WHERE status IN ('active','trial')''')
        active_subs = c.fetchone()['cnt']

        c.execute('''SELECT DATE(created_at) as day, COUNT(*) as cnt, COALESCE(SUM(amount),0) as revenue
                    FROM billing_invoices WHERE status='paid' AND created_at >= datetime('now','-30 days')
                    GROUP BY DATE(created_at) ORDER BY day''')
        daily_trend = [dict(r) for r in c.fetchall()]

    return jsonify({'success': True, 'total_paid': total_paid, 'total_revenue': total_revenue,
                    'revenue_30d': revenue_30d, 'active_subscriptions': active_subs,
                    'by_plan': by_plan, 'daily_trend': daily_trend})



@subscription_bp.route('/api/admin/subscriptions', methods=['GET'])
@require_permission('user:manage')
def api_admin_subscriptions():
    """运营方查看所有订阅"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''SELECT s.*, o.name as org_name, pt.name as plan_name, pt.plan_key
                    FROM subscriptions s
                    JOIN organizations o ON s.org_id=o.id
                    JOIN plan_tiers pt ON s.plan_id=pt.id
                    ORDER BY s.created_at DESC LIMIT 100''')
        rows = c.fetchall()
    return jsonify({'success': True, 'subscriptions': [dict(r) for r in rows]})