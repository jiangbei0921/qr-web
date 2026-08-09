"""
db_schema.py - 数据库初始化模块

这个文件负责创建和管理整个系统的数据库结构。
当系统启动时，会自动调用 init_db() 函数来确保所有必要的表都存在。

设计原则：
1. 幂等操作：所有 CREATE TABLE 都使用 IF NOT EXISTS，重复执行不会出错
2. 渐进式升级：通过 ALTER TABLE 添加新字段，旧数据不受影响
3. 自动索引：为常用查询字段自动创建索引，提高查询速度
"""

import sqlite3
import os
import logging
from routes.shared import get_db, DATABASE

logger = logging.getLogger(__name__)


def init_db():
    """初始化企业级数据库（幂等操作）
    
    这个函数是系统启动时最先执行的函数之一。
    它会创建所有必需的数据库表、索引和字段。
    因为是幂等操作，所以可以安全地重复执行。
    
    数据库中包含以下核心表：
    1. organizations - 组织/公司信息
    2. users - 用户账户信息
    3. qrcodes - 二维码数据
    4. forms - 表单定义
    5. workorders - 工单
    6. assets - 资产信息
    7. inspection_plans / inspection_records - 巡检计划与记录
    8. workflow_definitions / workflow_instances - 工作流定义与执行实例
    9. notifications - 通知消息
    10. subscriptions - 订阅信息
    11. files - 文件管理
    12. departments - 组织架构
    13. audit_logs - 审计日志（操作记录）
    """
    # 确保数据库文件所在目录存在
    db_dir = os.path.dirname(os.path.abspath(DATABASE))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with get_db() as conn:
        c = conn.cursor()

        # ============================================================
        # 1. 组织表（organizations）
        # 存储每个注册的公司/组织的基本信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 组织唯一ID，自动递增
            name TEXT UNIQUE NOT NULL,               -- 组织名称，必须唯一不能为空
            logo_url TEXT,                           -- 组织Logo的图片链接
            version_level INTEGER DEFAULT 0,         -- 版本等级（用于功能控制）
            expire_time DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 账户到期时间
            max_qrcodes INTEGER DEFAULT 100,         -- 最大二维码数量限制
            max_storage_gb INTEGER DEFAULT 1,        -- 最大存储空间（GB）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- 创建时间
        )''')

        # ============================================================
        # 2. 套餐计划表（plan_tiers）
        # 定义不同的订阅套餐，如免费版、专业版、企业版
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS plan_tiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,    -- 套餐唯一ID
            plan_key TEXT UNIQUE NOT NULL,            -- 套餐标识键（如 'free', 'pro', 'enterprise'）
            name TEXT NOT NULL,                       -- 套餐显示名称（如 '免费版', '专业版'）
            description TEXT DEFAULT '',              -- 套餐描述
            monthly_price REAL DEFAULT 0,             -- 月付价格（元）
            yearly_price REAL DEFAULT 0,              -- 年付价格（元）
            sort_order INTEGER DEFAULT 0,             -- 排序顺序（数字越小越靠前）
            is_enabled INTEGER DEFAULT 1,             -- 是否启用该套餐（0=禁用, 1=启用）
            features_json TEXT DEFAULT '{}',          -- 功能列表（JSON格式存储）
            quotas_json TEXT DEFAULT '{}',            -- 配额限制（JSON格式，如最大二维码数等）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ============================================================
        # 3. 订阅表（subscriptions）
        # 记录每个组织订阅了哪个套餐，以及订阅状态
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,                  -- 所属组织ID
            plan_id INTEGER NOT NULL,                 -- 订阅的套餐ID
            status TEXT DEFAULT 'trial',              -- 订阅状态：trial(试用), active(活跃), cancelled(已取消), expired(已过期)
            start_date DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 订阅开始日期
            end_date DATETIME,                        -- 订阅结束日期
            auto_renew INTEGER DEFAULT 0,             -- 是否自动续费（0=否, 1=是）
            payment_method TEXT DEFAULT '',           -- 支付方式
            last_payment_at DATETIME,                 -- 上次支付时间
            cancelled_at DATETIME,                    -- 取消时间
            cancel_reason TEXT DEFAULT '',            -- 取消原因
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),  -- 外键关联组织表
            FOREIGN KEY(plan_id) REFERENCES plan_tiers(id)     -- 外键关联套餐表
        )''')

        # ============================================================
        # 4. 账单发票表（billing_invoices）
        # 记录每次付费的账单明细
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS billing_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,                  -- 所属组织
            subscription_id INTEGER,                  -- 关联的订阅
            plan_id INTEGER,                          -- 关联的套餐
            amount REAL NOT NULL,                     -- 金额
            currency TEXT DEFAULT 'CNY',              -- 货币类型（默认人民币）
            status TEXT DEFAULT 'pending',            -- 状态：pending(待支付), paid(已支付), refunded(已退款)
            invoice_type TEXT DEFAULT 'new_subscription',  -- 发票类型：new_subscription(新订阅), renewal(续费), upgrade(升级)
            payment_method TEXT DEFAULT '',
            payment_gateway_txn_id TEXT DEFAULT '',   -- 支付网关交易ID
            paid_at DATETIME,                         -- 支付时间
            refunded_at DATETIME,                     -- 退款时间
            refund_amount REAL DEFAULT 0,             -- 退款金额
            refund_reason TEXT DEFAULT '',            -- 退款原因
            billing_period_start DATETIME,            -- 计费周期开始
            billing_period_end DATETIME,              -- 计费周期结束
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 5. 配额使用表（quota_usage）
        # 记录每个组织各项配额的实际使用量
        # 例如：已创建了多少二维码、使用了多少存储空间等
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS quota_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            quota_key TEXT NOT NULL,                  -- 配额键名（如 'max_qrcodes'）
            current_value INTEGER DEFAULT 0,          -- 当前使用量
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(org_id, quota_key),                -- 每个组织的每个配额只有一条记录
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 6. 用户表（users）
        # 存储所有用户账户信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 用户唯一ID
            username TEXT NOT NULL,                    -- 用户名
            email TEXT UNIQUE NOT NULL,                -- 邮箱（必须唯一，用于登录）
            password_hash TEXT NOT NULL,               -- 密码哈希值（不存储明文密码！）
            org_id INTEGER NOT NULL,                   -- 所属组织ID
            role_type TEXT DEFAULT 'member',           -- 角色类型：super_admin(超管), org_admin(组织管理员), editor(编辑), viewer(查看者)
            partition_id INTEGER DEFAULT 0,            -- 分区ID（用于多租户隔离）
            is_active INTEGER DEFAULT 1,               -- 是否激活（0=禁用, 1=正常）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 7. 二维码表（qrcodes）
        # 核心表之一，存储所有二维码的数据
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS qrcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 二维码唯一ID
            uuid_short TEXT UNIQUE NOT NULL,           -- 短码标识（用于生成短链接）
            org_id INTEGER NOT NULL,                   -- 所属组织
            partition_id INTEGER DEFAULT 0,            -- 分区ID
            title TEXT NOT NULL,                       -- 二维码标题
            biz_type TEXT DEFAULT 'media_only',        -- 业务类型：media_only(纯媒体), form(含表单), url(链接跳转)等
            content_json TEXT,                         -- 二维码内容（JSON格式）
            associated_form_id INTEGER,                -- 关联的表单ID
            current_status TEXT DEFAULT 'normal',      -- 当前状态：normal(正常), disabled(禁用), expired(过期)
            status_config TEXT,                        -- 状态配置（JSON）
            style_config TEXT,                         -- 样式配置（JSON，如颜色、Logo等）
            scan_count INTEGER DEFAULT 0,              -- 累计扫码次数
            is_active INTEGER DEFAULT 1,               -- 是否活跃
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 8. 表单表（forms）
        # 存储表单的定义信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 表单唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            form_name TEXT NOT NULL,                   -- 表单名称
            schema_json TEXT NOT NULL,                 -- 表单结构定义（JSON，包含字段类型、验证规则等）
            rule_settings TEXT,                        -- 表单规则设置（如提交限制、通知设置等）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 9. 表单提交记录表（form_submissions）
        # 存储用户提交的表单数据
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS form_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 提交记录唯一ID
            form_id INTEGER NOT NULL,                  -- 对应的表单ID
            qrcode_id INTEGER NOT NULL,                -- 关联的二维码ID（通过哪个二维码提交的）
            submitter_id INTEGER,                      -- 提交者用户ID
            payload_data TEXT NOT NULL,                -- 提交的数据内容（JSON）
            gps_location TEXT,                         -- GPS定位信息
            device_fingerprint TEXT,                   -- 设备指纹（用于防作弊）
            approval_state TEXT DEFAULT 'none',        -- 审批状态：none(无需审批), pending(待审批), approved(已通过), rejected(已拒绝)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(form_id) REFERENCES forms(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id)
        )''')

        # ============================================================
        # 10. 活码（动态链接）表（dynamic_links）
        # 活码是一种特殊的二维码，扫码后跳转的链接可以动态修改
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS dynamic_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 活码唯一ID
            short_code TEXT UNIQUE NOT NULL,           -- 短码（用于生成短链接，如 /s/abc123）
            qrcode_id INTEGER,                         -- 关联的二维码ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            title TEXT,                                -- 活码标题
            target_url TEXT,                           -- 目标跳转URL
            target_type TEXT DEFAULT 'url',            -- 目标类型：url(网址), asset(资产), form(表单)等
            target_content TEXT,                       -- 目标内容
            expire_time DATETIME,                      -- 过期时间
            max_scans INTEGER DEFAULT 0,               -- 最大扫码次数（0表示无限制）
            scan_count INTEGER DEFAULT 0,              -- 已扫码次数
            rule_json TEXT,                            -- 跳转规则（JSON，如按地区/设备分流）
            status TEXT DEFAULT 'active',              -- 状态：active(活跃), expired(过期), disabled(禁用)
            created_by INTEGER,                        -- 创建者ID
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id)
        )''')
        # 为活码的短码和所属组织创建索引，加速查询
        c.execute('CREATE INDEX IF NOT EXISTS idx_dynamic_links_short_code ON dynamic_links(short_code)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_dynamic_links_org ON dynamic_links(org_id)')

        # ============================================================
        # 11. 扫码日志表（scan_logs）
        # 记录每次扫码的详细信息，用于数据分析
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS scan_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 日志唯一ID
            qrcode_id INTEGER NOT NULL,                -- 被扫的二维码ID
            dynamic_link_id INTEGER,                   -- 如果是活码扫码，记录活码ID
            scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 扫码时间
            ip TEXT,                                   -- 扫码者IP地址
            city TEXT,                                 -- 根据IP推断的城市
            country TEXT DEFAULT 'CN',                 -- 国家
            device TEXT,                               -- 设备类型（mobile/desktop）
            browser TEXT,                              -- 浏览器类型
            os TEXT,                                   -- 操作系统
            referer TEXT,                              -- 来源页面
            user_agent TEXT,                           -- 完整的User-Agent字符串
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_scan_logs_qrcode ON scan_logs(qrcode_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_scan_logs_time ON scan_logs(scan_time)')

        # ============================================================
        # 12. 标签系统（tags + qrcode_tags）
        # 用于给二维码打标签，方便分类管理
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 标签唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            name TEXT NOT NULL,                        -- 标签名称
            color TEXT DEFAULT '#1677FF',              -- 标签颜色（十六进制）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(org_id, name)                       -- 同一组织内标签名不能重复
        )''')

        # 二维码与标签的多对多关联表
        c.execute('''CREATE TABLE IF NOT EXISTS qrcode_tags (
            qrcode_id INTEGER NOT NULL,                -- 二维码ID
            tag_id INTEGER NOT NULL,                   -- 标签ID
            PRIMARY KEY(qrcode_id, tag_id),            -- 联合主键，确保不重复关联
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id),
            FOREIGN KEY(tag_id) REFERENCES tags(id)
        )''')

        # ============================================================
        # 13. 审计日志表（audit_logs）
        # 记录所有重要操作，用于安全审计和问题追踪
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 日志唯一ID
            org_id INTEGER,                            -- 所属组织
            user_id INTEGER,                           -- 操作者ID
            action TEXT NOT NULL,                      -- 操作类型（如 'create_qrcode', 'delete_form'）
            target_type TEXT,                          -- 操作目标类型（如 'qrcode', 'form'）
            target_id INTEGER,                         -- 操作目标ID
            detail TEXT,                               -- 操作详情（JSON格式）
            ip TEXT,                                   -- 操作者IP
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_logs(org_id, created_at)')

        # 为审计日志表补充字段（兼容旧版本数据库）
        for col_stmt in [
            'ALTER TABLE audit_logs ADD COLUMN resource_type TEXT',
            'ALTER TABLE audit_logs ADD COLUMN resource_id INTEGER',
            'ALTER TABLE audit_logs ADD COLUMN before_data TEXT',
            'ALTER TABLE audit_logs ADD COLUMN after_data TEXT',
            'ALTER TABLE audit_logs ADD COLUMN user_agent TEXT'
        ]:
            try:
                c.execute(col_stmt)
            except sqlite3.OperationalError:
                pass  # 字段已存在时忽略错误

        # 创建审计日志的多维度索引
        for idx_stmt in [
            'CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_logs(resource_type, resource_id)',
            'CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC)'
        ]:
            try:
                c.execute(idx_stmt)
            except sqlite3.OperationalError:
                pass

        # ============================================================
        # 为已有表补充字段（数据库版本升级兼容）
        # 这些 ALTER TABLE 语句确保旧版本数据库也能正常使用新功能
        # ============================================================
        for col_stmt in [
            'ALTER TABLE qrcodes ADD COLUMN tags TEXT',
            'ALTER TABLE qrcodes ADD COLUMN archive_status INTEGER DEFAULT 0',
            'ALTER TABLE qrcodes ADD COLUMN category TEXT',
            'ALTER TABLE qrcodes ADD COLUMN creator_id INTEGER',
            'ALTER TABLE qrcodes ADD COLUMN dynamic_link_id INTEGER',
            'ALTER TABLE qrcodes ADD COLUMN status TEXT DEFAULT \'draft\'',
            'ALTER TABLE qrcodes ADD COLUMN published_at TIMESTAMP',
            'ALTER TABLE qrcodes ADD COLUMN expired_at TIMESTAMP',
            'ALTER TABLE qrcodes ADD COLUMN archived_at TIMESTAMP',
            'ALTER TABLE qrcodes ADD COLUMN deleted_at TIMESTAMP',
            'ALTER TABLE qrcodes ADD COLUMN review_user_id INTEGER',
            'ALTER TABLE qrcodes ADD COLUMN review_comment TEXT',
            'ALTER TABLE qrcodes ADD COLUMN is_deleted INTEGER DEFAULT 0',
            'ALTER TABLE qrcodes ADD COLUMN deleted_by INTEGER'
        ]:
            try:
                c.execute(col_stmt)
            except sqlite3.OperationalError:
                pass

        # 为表单表补充字段
        for col_stmt in [
            'ALTER TABLE forms ADD COLUMN is_deleted INTEGER DEFAULT 0',
            'ALTER TABLE forms ADD COLUMN deleted_by INTEGER',
            'ALTER TABLE forms ADD COLUMN deleted_at TIMESTAMP',
            'ALTER TABLE files ADD COLUMN is_deleted INTEGER DEFAULT 0',
            'ALTER TABLE files ADD COLUMN deleted_by INTEGER',
            'ALTER TABLE files ADD COLUMN deleted_at TIMESTAMP',
            'ALTER TABLE workorders ADD COLUMN is_deleted INTEGER DEFAULT 0',
            'ALTER TABLE workorders ADD COLUMN deleted_by INTEGER',
            'ALTER TABLE workorders ADD COLUMN deleted_at TIMESTAMP',
            'ALTER TABLE inspection_plans ADD COLUMN is_deleted INTEGER DEFAULT 0',
            'ALTER TABLE inspection_plans ADD COLUMN deleted_by INTEGER',
            'ALTER TABLE inspection_plans ADD COLUMN deleted_at TIMESTAMP'
        ]:
            try:
                c.execute(col_stmt)
            except sqlite3.OperationalError:
                pass

        # 为软删除功能创建索引
        for idx_stmt in [
            'CREATE INDEX IF NOT EXISTS idx_qrcodes_deleted ON qrcodes(org_id, is_deleted, deleted_at)',
            'CREATE INDEX IF NOT EXISTS idx_forms_deleted ON forms(org_id, is_deleted, deleted_at)',
            'CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(org_id, is_deleted, deleted_at)',
            'CREATE INDEX IF NOT EXISTS idx_workorders_deleted ON workorders(org_id, is_deleted, deleted_at)',
            'CREATE INDEX IF NOT EXISTS idx_inspection_plans_deleted ON inspection_plans(org_id, is_deleted, deleted_at)'
        ]:
            try:
                c.execute(idx_stmt)
            except sqlite3.OperationalError:
                pass

        # ============================================================
        # 14. 文件表（files）
        # 存储上传文件的信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 文件唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            name TEXT NOT NULL,                        -- 存储文件名
            original_name TEXT,                        -- 原始文件名
            path TEXT NOT NULL,                        -- 文件存储路径
            file_type TEXT,                            -- 文件类型（扩展名）
            mime_type TEXT,                            -- MIME类型
            size INTEGER DEFAULT 0,                    -- 文件大小（字节）
            version INTEGER DEFAULT 1,                 -- 版本号
            description TEXT,                          -- 文件描述
            tags TEXT,                                 -- 标签
            created_by INTEGER,                        -- 上传者
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_files_org ON files(org_id, created_at)')

        # 补充用户表字段
        for col_stmt in [
            'ALTER TABLE forms ADD COLUMN status TEXT DEFAULT \'active\'',
            'ALTER TABLE forms ADD COLUMN updated_at TIMESTAMP',
            'ALTER TABLE users ADD COLUMN last_login TIMESTAMP',       # 最后登录时间
            'ALTER TABLE users ADD COLUMN invited_by INTEGER',         # 邀请人
            'ALTER TABLE users ADD COLUMN preferred_lang TEXT DEFAULT \'zh\''  # 偏好语言
        ]:
            try:
                c.execute(col_stmt)
            except sqlite3.OperationalError:
                pass

        # 创建常用查询索引
        try:
            c.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_qrcodes_uuid ON qrcodes(uuid_short)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_forms_org_id ON forms(org_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id ON form_submissions(form_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_form_submissions_qrcode_id ON form_submissions(qrcode_id)')
        except sqlite3.OperationalError as e:
            logger.warning(f"索引创建跳过: {e}")

        # ============================================================
        # 15. 资产表（assets）
        # 存储企业固定资产信息，每个资产可绑定一个二维码
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 资产唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            name TEXT NOT NULL,                        -- 资产名称
            asset_code TEXT UNIQUE,                    -- 资产编码（唯一标识）
            category TEXT,                             -- 资产分类
            location TEXT,                             -- 存放位置
            status TEXT DEFAULT 'normal',              -- 状态：normal(正常), repairing(维修中), scrapped(已报废)
            description TEXT,                          -- 描述
            qrcode_id INTEGER,                         -- 绑定的二维码ID
            purchase_date TEXT,                        -- 购置日期
            value REAL DEFAULT 0,                      -- 资产价值
            responsible_user_id INTEGER,               -- 责任人ID
            created_by INTEGER,                        -- 创建者
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_assets_org ON assets(org_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_assets_code ON assets(asset_code)')

        # ============================================================
        # 16. 巡检计划表（inspection_plans）
        # 定义资产的定期巡检计划
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS inspection_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 计划唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            qrcode_id INTEGER,                         -- 关联的二维码ID
            asset_id INTEGER,                          -- 关联的资产ID
            cycle_type TEXT DEFAULT 'weekly',          -- 巡检周期类型：daily(每日), weekly(每周), monthly(每月)
            frequency_days INTEGER DEFAULT 7,          -- 巡检频率（天）
            assigned_user_id INTEGER,                  -- 指派的巡检人员ID
            last_completed TIMESTAMP,                  -- 上次完成时间
            is_active INTEGER DEFAULT 1,               -- 是否启用
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id),
            FOREIGN KEY(asset_id) REFERENCES assets(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_inspection_plans_org ON inspection_plans(org_id)')

        for col_stmt in [
            'ALTER TABLE inspection_plans ADD COLUMN asset_id INTEGER',
            'ALTER TABLE inspection_plans ADD COLUMN is_active INTEGER DEFAULT 1'
        ]:
            try:
                c.execute(col_stmt)
            except sqlite3.OperationalError:
                pass

        # ============================================================
        # 17. 巡检记录表（inspection_records）
        # 存储每次巡检的执行结果
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS inspection_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 记录唯一ID
            plan_id INTEGER,                           -- 关联的巡检计划ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            qrcode_id INTEGER,                         -- 扫码的二维码ID
            asset_id INTEGER,                          -- 被巡检的资产ID
            inspector_id INTEGER NOT NULL,             -- 巡检人员ID
            result TEXT DEFAULT 'normal',              -- 巡检结果：normal(正常), abnormal(异常)
            note TEXT,                                 -- 备注说明
            images TEXT,                               -- 现场照片（JSON数组）
            gps_location TEXT,                         -- GPS定位
            inspected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 巡检时间
            FOREIGN KEY(plan_id) REFERENCES inspection_plans(id),
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id),
            FOREIGN KEY(asset_id) REFERENCES assets(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_inspection_records_plan ON inspection_records(plan_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_inspection_records_asset ON inspection_records(asset_id)')

        # ============================================================
        # 18. 工单表（workorders）
        # 存储维修、投诉等工单信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS workorders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 工单唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            title TEXT NOT NULL,                       -- 工单标题
            qrcode_id INTEGER,                         -- 关联的二维码ID
            asset_id INTEGER,                          -- 关联的资产ID
            status TEXT DEFAULT 'open',                -- 状态：open(待处理), processing(处理中), resolved(已解决), closed(已关闭)
            priority TEXT DEFAULT 'normal',            -- 优先级：normal(普通), high(高), urgent(紧急)
            assignee_id INTEGER,                       -- 指派的处理人ID
            created_by INTEGER,                        -- 创建者ID
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id),
            FOREIGN KEY(asset_id) REFERENCES assets(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_workorders_org ON workorders(org_id)')

        for col_stmt in [
            'ALTER TABLE workorders ADD COLUMN description TEXT',       # 工单描述
            'ALTER TABLE workorders ADD COLUMN asset_id INTEGER',
            'ALTER TABLE workorders ADD COLUMN resolved_at TIMESTAMP',  # 解决时间
            'ALTER TABLE workorders ADD COLUMN resolution_note TEXT',   # 解决方案说明
            'ALTER TABLE workorders ADD COLUMN images TEXT',            # 相关图片
            'ALTER TABLE workorders ADD COLUMN updated_at TIMESTAMP'
        ]:
            try:
                c.execute(col_stmt)
            except sqlite3.OperationalError:
                pass

        # ============================================================
        # 19. 资源版本表（resource_versions）
        # 存储资源的版本快照，支持版本回滚
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS resource_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 版本唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            resource_type TEXT NOT NULL,               -- 资源类型（如 'qrcode', 'form'）
            resource_id INTEGER NOT NULL,              -- 资源ID
            version INTEGER NOT NULL DEFAULT 1,        -- 版本号
            snapshot TEXT NOT NULL,                    -- 快照数据（JSON）
            content_hash TEXT,                         -- 内容哈希值（用于快速比较）
            operator INTEGER,                          -- 操作者ID
            remark TEXT,                               -- 备注
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        try:
            c.execute('CREATE INDEX IF NOT EXISTS idx_rv_resource ON resource_versions(org_id, resource_type, resource_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_rv_created ON resource_versions(created_at)')
        except sqlite3.OperationalError:
            pass

        # ============================================================
        # 20. 通知表（notifications）
        # 存储系统通知消息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 通知唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            user_id INTEGER,                           -- 接收用户ID（NULL表示发给组织所有人）
            title TEXT NOT NULL,                       -- 通知标题
            content TEXT,                              -- 通知内容
            category TEXT DEFAULT 'system',            -- 分类：system(系统), workorder(工单), inspection(巡检)等
            level TEXT DEFAULT 'info',                 -- 级别：info(信息), warning(警告), error(错误)
            link TEXT,                                 -- 关联链接
            source_type TEXT,                          -- 来源类型
            source_id INTEGER,                         -- 来源ID
            is_read INTEGER DEFAULT 0,                 -- 是否已读
            is_archived INTEGER DEFAULT 0,             -- 是否已归档
            is_deleted INTEGER DEFAULT 0,              -- 是否已删除
            read_at TIMESTAMP,                         -- 阅读时间
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_notifications_org_user ON notifications(org_id, user_id, is_read)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)')

        # ============================================================
        # 21. 通知设置表（notification_settings）
        # 用户的个性化通知偏好设置
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS notification_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,                    -- 通知分类
            channel_inapp INTEGER DEFAULT 1,           -- 站内通知开关
            channel_email INTEGER DEFAULT 0,           -- 邮件通知开关
            channel_webhook INTEGER DEFAULT 0,         -- Webhook通知开关
            channel_sms INTEGER DEFAULT 0,             -- 短信通知开关
            channel_wechat INTEGER DEFAULT 0,          -- 微信通知开关
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(org_id, user_id, category),
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 22. Webhook配置表（webhook_configs）
        # 配置第三方系统回调地址
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS webhook_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            name TEXT NOT NULL,                        -- Webhook名称
            url TEXT NOT NULL,                         -- 回调URL
            secret TEXT,                               -- 密钥（用于签名验证）
            events TEXT,                               -- 触发事件列表（JSON数组）
            is_active INTEGER DEFAULT 1,               -- 是否启用
            last_triggered_at TIMESTAMP,               -- 上次触发时间
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 23. 组织架构/部门表（departments）
        # 存储企业的组织架构树
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 部门唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            parent_id INTEGER,                         -- 父部门ID（NULL表示顶级部门）
            name TEXT NOT NULL,                        -- 部门名称
            node_type TEXT DEFAULT 'department',       -- 节点类型：department(部门), team(团队), position(岗位), virtual(虚拟组织)
            path TEXT,                                 -- 路径（如 /1/5/8/，表示部门层级关系）
            depth INTEGER DEFAULT 0,                   -- 层级深度（0为顶级）
            sort_order INTEGER DEFAULT 0,              -- 排序号
            leader_id INTEGER,                         -- 部门负责人ID
            leader_name TEXT,                          -- 部门负责人姓名
            description TEXT,                          -- 部门描述
            is_deleted INTEGER DEFAULT 0,              -- 软删除标记
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_departments_org ON departments(org_id, is_deleted)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_departments_path ON departments(path)')

        # ============================================================
        # 24. 工作流定义表（workflow_definitions）
        # 存储自动化工作流的定义
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS workflow_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 工作流唯一ID
            org_id INTEGER NOT NULL,                   -- 所属组织
            name TEXT NOT NULL,                        -- 工作流名称
            description TEXT,                          -- 描述
            trigger_type TEXT NOT NULL,                -- 触发类型：qrcode:scan(扫码触发), schedule:time(定时触发), webhook:received(Webhook触发)等
            trigger_config TEXT,                       -- 触发配置（JSON）
            current_version INTEGER DEFAULT 1,         -- 当前版本号
            is_enabled INTEGER DEFAULT 1,              -- 是否启用
            is_deleted INTEGER DEFAULT 0,              -- 软删除
            created_by INTEGER,                        -- 创建者
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_wf_def_org ON workflow_definitions(org_id, is_deleted)')

        # ============================================================
        # 25. 工作流版本表（workflow_versions）
        # 存储工作流的每个版本（节点和边的JSON定义）
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS workflow_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 版本唯一ID
            workflow_id INTEGER NOT NULL,              -- 所属工作流
            version INTEGER NOT NULL,                  -- 版本号
            nodes_json TEXT,                           -- 节点定义（JSON数组，包含每个步骤的类型和配置）
            edges_json TEXT,                           -- 边定义（JSON数组，包含节点间的连接关系）
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(workflow_id) REFERENCES workflow_definitions(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_wf_ver_wf ON workflow_versions(workflow_id, version)')

        # ============================================================
        # 26. 工作流实例表（workflow_instances）
        # 存储每次工作流执行的具体实例
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS workflow_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,     -- 实例唯一ID
            workflow_id INTEGER NOT NULL,              -- 所属工作流定义
            org_id INTEGER NOT NULL,                   -- 所属组织
            status TEXT DEFAULT 'running',             -- 状态：running(运行中), completed(已完成), failed(失败)
            current_node TEXT,                         -- 当前执行到的节点
            context_data TEXT,                         -- 上下文数据（JSON，存储执行过程中的变量）
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY(workflow_id) REFERENCES workflow_definitions(id),
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_wf_inst_wf ON workflow_instances(workflow_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_wf_inst_org ON workflow_instances(org_id)')

        # ============================================================
        # 27. 工作流执行日志表（workflow_execution_logs）
        # 记录工作流每个步骤的执行情况
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS workflow_execution_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL,              -- 所属实例
            node_id TEXT,                              -- 节点ID
            action TEXT,                               -- 执行的动作
            result TEXT,                               -- 执行结果
            error_message TEXT,                        -- 错误信息（如有）
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY(instance_id) REFERENCES workflow_instances(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_wf_exec_log_inst ON workflow_execution_logs(instance_id)')

        # ============================================================
        # 28. Webhook日志表（workflow_webhook_logs）
        # 记录Webhook触发工作流的请求日志
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS workflow_webhook_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            request_method TEXT,                       -- 请求方法（GET/POST等）
            request_headers TEXT,                      -- 请求头
            request_body TEXT,                         -- 请求体
            response_status INTEGER,                   -- 响应状态码
            response_body TEXT,                        -- 响应体
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(workflow_id) REFERENCES workflow_definitions(id)
        )''')

        # ============================================================
        # 29. 批量任务表（batch_tasks）
        # 存储批量操作任务（如批量删除、批量修改等）
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS batch_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER,
            task_type TEXT NOT NULL,                   -- 任务类型：delete, modify, export等
            resource_type TEXT,                        -- 资源类型：qrcode, form, file等
            params_json TEXT,                          -- 任务参数（JSON）
            status TEXT DEFAULT 'pending',             -- 状态：pending, running, completed, failed
            total_count INTEGER DEFAULT 0,            -- 总任务数量
            success_count INTEGER DEFAULT 0,          -- 成功数量
            failure_count INTEGER DEFAULT 0,          -- 失败数量
            result_json TEXT,                          -- 执行结果（JSON）
            error_message TEXT,                        -- 错误信息
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP                     -- 完成时间
        )''')

        # ============================================================
        # 30. 合集表（collections）和 合集内容表（collection_items）
        # 用于将多个二维码打包成一个合集（类似文件夹功能）
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            cover_image TEXT,
            is_public INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_collections_org ON collections(org_id)')

        c.execute('''CREATE TABLE IF NOT EXISTS collection_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL,
            qrcode_id INTEGER NOT NULL,
            sort_order INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(collection_id) REFERENCES collections(id),
            FOREIGN KEY(qrcode_id) REFERENCES qrcodes(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_collection_items_cid ON collection_items(collection_id)')

        # ============================================================
        # 31. OAuth2 客户端表（oauth2_clients）
        # 存储 OpenAPI 的 OAuth2 客户端注册信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS oauth2_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            client_id TEXT UNIQUE NOT NULL,
            client_secret TEXT NOT NULL,
            client_name TEXT NOT NULL,
            redirect_uris TEXT,
            grant_types TEXT DEFAULT 'authorization_code',
            scopes TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 32. OAuth2 授权码表（oauth2_auth_codes）
        # 存储 OAuth2 授权流程中生成的临时授权码
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS oauth2_auth_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            scopes TEXT DEFAULT '',
            expires_at TIMESTAMP NOT NULL,
            is_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ============================================================
        # 33. OAuth2 令牌表（oauth2_tokens）
        # 存储 OAuth2 流程中生成的访问令牌和刷新令牌
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS oauth2_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            access_token TEXT UNIQUE NOT NULL,
            refresh_token TEXT UNIQUE,
            token_type TEXT DEFAULT 'Bearer',
            scopes TEXT DEFAULT '',
            expires_at TIMESTAMP,
            is_revoked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ============================================================
        # 34. API Key 表（api_keys）
        # 存储用户创建的 API 密钥，用于 OpenAPI 认证
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            api_secret TEXT,
            permissions TEXT DEFAULT '[]',
            is_active INTEGER DEFAULT 1,
            last_used_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys(org_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(api_key)')

        # ============================================================
        # 35. API 调用日志表（api_call_logs）
        # 记录所有通过 OpenAPI 的调用记录，用于计费和监控
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS api_call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            api_key_id INTEGER,
            endpoint TEXT NOT NULL,
            method TEXT NOT NULL,
            status_code INTEGER,
            response_time_ms INTEGER,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_api_call_logs_org ON api_call_logs(org_id, created_at)')

        # ============================================================
        # 36. 用户会话表（user_sessions）
        # 存储用户的登录会话信息，支持多设备登录管理
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_token TEXT UNIQUE NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            device_info TEXT,
            is_active INTEGER DEFAULT 1,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        # ============================================================
        # 37. 系统配置表（system_config）
        # 存储系统级别的配置项，如邮件服务器、短信配置等
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS system_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT UNIQUE NOT NULL,
            config_value TEXT,
            config_type TEXT DEFAULT 'string',
            description TEXT,
            is_public INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by INTEGER
        )''')

        # ============================================================
        # 38. 模板表（templates）
        # 存储二维码模板信息
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            thumbnail TEXT,
            config_json TEXT NOT NULL,
            is_public INTEGER DEFAULT 0,
            use_count INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ============================================================
        # 39. 收藏表（favorites）
        # 存储用户收藏的二维码/表单/工单等
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, resource_type, resource_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        # ============================================================
        # 40. 邀请码表（invite_codes）
        # 存储组织邀请新成员的邀请码
        # ============================================================
        c.execute('''CREATE TABLE IF NOT EXISTS invite_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            role_type TEXT DEFAULT 'member',
            max_uses INTEGER DEFAULT 0,
            use_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            expires_at TIMESTAMP,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        )''')

        # ============================================================
        # 提交所有数据库变更
        # ============================================================
        # 41. search_history
        c.execute('''CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            keyword TEXT NOT NULL,
            resource_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_search_history_org_user ON search_history(org_id, user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_search_history_keyword ON search_history(keyword)')

        # 42. saved_searches
        c.execute('''CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            query_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        # 43. batch_audit_log
        c.execute('''CREATE TABLE IF NOT EXISTS batch_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            user_id INTEGER,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id INTEGER,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_batch_audit_log_task ON batch_audit_log(task_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_batch_audit_log_created ON batch_audit_log(created_at DESC)')

        # 44. batch_task_items
        c.execute('''CREATE TABLE IF NOT EXISTS batch_task_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            title TEXT,
            action TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            error_msg TEXT,
            snapshot_json TEXT,
            processed_at TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES batch_tasks(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_batch_task_items_task ON batch_task_items(task_id)')

        # 45. user_dashboard_config
        c.execute('''CREATE TABLE IF NOT EXISTS user_dashboard_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            layout_json TEXT,
            theme TEXT DEFAULT 'light',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        conn.commit()

    logger.info("数据库初始化完成（所有表和索引已就绪）")