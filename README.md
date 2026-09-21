# 智码云（SmartCode）企业级二维码管理平台 v2.0

## 项目简介

智码云（SmartCode）是一个基于 **Python Flask** 框架构建的企业级二维码全生命周期管理平台。它不仅提供了强大的二维码生成与美化能力，更围绕二维码构建了完整的业务生态——包括表单收集、工单流转、资产管理、巡检计划、工作流自动化、组织架构权限管理、多语言国际化、开放 API 平台以及订阅计费系统。

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | Flask 2.3.3 |
| 数据库 | SQLite（通过 sqlite3 模块） |
| 跨域支持 | Flask-CORS 4.0.0 |
| 二维码生成 | qrcode 7.4.2 |
| 图像处理 | Pillow 10.0.0 |
| 名片格式 | vobject 0.9.6.1 |
| 国际化 | 自研 i18n 模块（支持 JSON 语言包） |
| 认证 | Session + 密码哈希（Werkzeug） |
| 开放 API | API Key + JWT + OAuth2 |

## 项目结构

```
qr-web/
├── app.py                      # Flask 应用入口，蓝图注册，全局配置
├── db_schema.py                # 数据库初始化（建表、索引、字段升级）
├── backend_i18n.py             # 后端国际化翻译模块
├── requirements.txt            # Python 依赖包列表
├── test_auth.py                # 用户认证功能测试脚本
├── smartcode.db                # SQLite 数据库文件
├── routes/                     # 功能模块路由（蓝图）
│   ├── shared.py               # 共享工具：数据库、认证、权限、二维码生成、通知等
│   ├── auth.py                 # 用户认证：注册、登录、登出
│   ├── qrcode.py               # 二维码管理：生成、扫描、活码、样式配置
│   ├── form.py                 # 表单系统：创建、提交、数据收集
│   ├── workorder.py            # 工单系统：创建、分配、处理
│   ├── asset.py                # 资产管理：资产CRUD、二维码绑定
│   ├── inspection.py           # 巡检管理：巡检计划、记录管理
│   ├── department.py           # 组织架构：部门树、人员管理
│   ├── notification.py         # 通知系统：站内通知、Webhook
│   ├── workflow.py             # 工作流定义：流程模板管理
│   ├── workflow_engine.py      # 工作流引擎：流程执行、状态流转
│   ├── subscription.py         # 订阅计费：套餐管理、付费
│   ├── workspace.py            # 工作台：仪表盘、统一搜索
│   ├── open_api.py             # 开放平台：API Key、JWT、OAuth2
│   ├── file_mgr.py             # 文件管理：上传、下载、文件库
│   ├── admin.py                # 管理后台主入口
│   ├── admin_audit.py          # 审计日志管理
│   ├── admin_batch.py          # 批量操作管理
│   ├── admin_recycle.py        # 回收站管理（软删除恢复）
│   ├── admin_tag.py            # 标签管理
│   ├── admin_template.py       # 模板管理
│   ├── admin_user.py           # 用户管理
│   └── admin_version.py        # 版本管理
├── templates/                  # HTML 前端模板
│   ├── home.html               # 营销落地页
│   ├── index.html              # 管理后台首页
│   ├── dashboard.html          # 仪表盘
│   ├── scene.html              # 应用场景展示
│   ├── template_center.html    # 模板中心
│   ├── collection_editor.html  # 合集编辑器
│   └── my_space.html           # 个人空间
├── static/                     # 静态资源
│   ├── style.css               # 样式表
│   ├── app.js                  # 前端交互脚本
│   └── lang/                   # 多语言包
│       ├── zh.json             # 中文
│       ├── en.json             # 英文
│       ├── ja.json             # 日文
│       └── ko.json             # 韩文
└── uploads/                    # 上传文件目录
```

## 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动应用

```bash
python app.py
```

### 访问地址

```
http://localhost:5000
```

## 功能模块详解

### 1. 二维码管理（QR Code）

- **静态码生成**：支持文本、URL、邮件、短信、名片（vCard）、WiFi 等多种类型
- **活码（动态码）**：扫码后跳转链接可动态修改，支持按地区/设备分流
- **美化定制**：前景色/背景色、圆角/方形样式、Logo 嵌入、容错率选择、尺寸调整
- **批量生成**：CSV 文件导入批量生成二维码
- **多格式导出**：PNG、SVG 格式
- **扫码统计**：实时扫码次数、地理位置、设备类型等数据分析
- **标签分类**：支持对二维码打标签，便于分类管理
- **软删除与回收站**：删除的二维码可恢复

### 2. 表单系统（Form）

- **可视化表单创建**：拖拽式表单设计器，支持多种字段类型
- **数据收集**：扫码后填写表单，支持 GPS 定位、设备指纹
- **审批流程**：提交后支持审批（待审批/已通过/已拒绝）
- **规则设置**：提交限制、通知设置等

### 3. 工单系统（Work Order）

- **工单创建**：基于二维码扫码创建工单
- **工单分配**：指派处理人员
- **状态流转**：待处理 → 处理中 → 已完成
- **软删除支持**

### 4. 资产管理（Asset）

- **资产登记**：资产名称、编码、分类、位置、价值等
- **二维码绑定**：每个资产可绑定专属二维码
- **责任人指定**：明确资产责任人
- **全生命周期追踪**：正常 → 维修中 → 已报废

### 5. 巡检计划（Inspection）

- **巡检计划**：支持每日/每周/每月等多种周期
- **巡检记录**：每次巡检结果记录
- **资产关联**：巡检计划绑定具体资产
- **人员指派**：指定巡检执行人员

### 6. 工作流引擎（Workflow）

- **流程定义**：可视化配置审批流程步骤
- **流程实例**：每个流程实例跟踪执行状态
- **Webhook 通知**：流程节点变更时自动通知
- **超时处理**：支持设置节点超时自动处理

### 7. 组织架构与权限（RBAC）

- **部门管理**：树形组织架构
- **角色权限**：超管 → 组织管理员 → 编辑者 → 查看者
- **多租户隔离**：分区（partition）级别数据隔离

### 8. 多语言国际化（i18n）

- **支持语言**：中文（zh）、英文（en）、日文（ja）、韩文（ko）
- **自动检测**：URL 参数 → Session → Accept-Language 头，三级优先级
- **JSON 语言包**：前后端统一使用 JSON 格式语言包
- **热更新**：开发环境支持清除缓存

### 9. 开放 API 平台（OpenAPI）

- **API Key 认证**：为第三方应用生成 API 密钥
- **JWT 认证**：无状态 Token 认证
- **OAuth2 认证**：标准 OAuth2 授权流程
- **接口文档**：标准化的 API 接口

### 10. 订阅与计费（Subscription）

- **套餐管理**：免费版、专业版、企业版多级套餐
- **配额控制**：二维码数量、存储空间等配额限制
- **账单系统**：发票记录、支付状态跟踪
- **自动续费**：支持自动续费配置

### 11. 文件管理（File）

- **文件上传**：支持多种格式上传
- **文件预览**：在线预览文件内容
- **版本管理**：文件版本追踪
- **软删除**：删除文件可恢复

### 12. 通知系统（Notification）

- **站内通知**：系统消息、工单提醒等
- **Webhook 推送**：支持外部系统回调通知
- **异步发送**：多线程异步处理，不阻塞主流程

### 13. 管理后台（Admin）

- **用户管理**：查看、编辑、禁用/启用用户
- **审计日志**：记录所有重要操作，支持多维度查询
- **批量操作**：批量导入、导出、删除
- **回收站**：软删除数据恢复
- **标签管理**：统一标签分类管理
- **模板管理**：二维码模板库管理

## 数据库设计

项目使用 SQLite 数据库，包含以下核心数据表：

| 表名 | 说明 |
|------|------|
| `organizations` | 组织/公司信息 |
| `users` | 用户账户 |
| `plan_tiers` | 套餐计划定义 |
| `subscriptions` | 订阅记录 |
| `billing_invoices` | 账单发票 |
| `quota_usage` | 配额使用量 |
| `qrcodes` | 二维码数据 |
| `dynamic_links` | 活码（动态链接） |
| `scan_logs` | 扫码日志 |
| `forms` | 表单定义 |
| `form_submissions` | 表单提交记录 |
| `tags` / `qrcode_tags` | 标签系统 |
| `assets` | 资产信息 |
| `inspection_plans` | 巡检计划 |
| `inspection_records` | 巡检记录 |
| `workorders` | 工单 |
| `workflow_definitions` | 工作流定义 |
| `workflow_instances` | 工作流执行实例 |
| `notifications` | 通知消息 |
| `files` | 文件管理 |
| `departments` | 部门组织架构 |
| `audit_logs` | 审计日志 |

## 安全特性

- **密码哈希存储**：使用 Werkzeug 安全哈希，不存储明文密码
- **Session Cookie 安全**：HttpOnly、SameSite、Secure 属性配置
- **安全响应头**：Cache-Control、X-Content-Type-Options、X-Frame-Options、X-XSS-Protection
- **CORS 控制**：通过 Flask-CORS 管理跨域访问
- **软删除机制**：数据删除后进入回收站，可恢复，防止误删
- **审计日志**：完整记录用户操作，便于安全审计

## 国际化（i18n）使用说明

### 后端使用

```python
from backend_i18n import t

# 基本翻译
t('auth.loginFailed')  # 返回对应语言的翻译文本

# 带参数的翻译
t('qrcode.scanCount', params={'count': 100})

# 带默认值的翻译
from backend_i18n import t_or
t_or('some.key', '默认文本')
```

### 前端使用

前端通过 `data-i18n` 属性标记需要翻译的元素，JavaScript 在页面加载时自动替换。

## 运行测试

```bash
# 启动应用后，另开终端运行测试
python test_auth.py
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SMARTCODE_SECRET_KEY` | Flask 密钥 | 随机生成 |
| `SMARTCODE_UPLOAD_FOLDER` | 上传文件目录 | `uploads` |
| `SMARTCODE_DATABASE` | 数据库文件路径 | `smartcode.db` |
| `SMARTCODE_DEBUG` | 调试模式 | `False` |

## License

内部项目，仅供团队使用。