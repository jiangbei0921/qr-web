# 智码云 SmartCode

> 企业级二维码管理与数字化运营平台（v2.0）—— 基于 Flask 的全栈应用。

智码云将二维码从「生成工具」升级为「业务入口」：扫码后可承接表单收集、工单流转、资产巡检、工作流自动化与企业组织协同，并对外提供开放平台（API Key / JWT / OAuth2）。

---

## 功能模块

| 模块 | 说明 |
| --- | --- |
| 二维码 QRCode | 静态码 / 活码生成、美化（颜色、圆角、Logo、容错率）、批量导入、PNG/SVG 导出 |
| 表单 Form | 自定义表单创建、数据收集与导出（vCard / 日历等） |
| 工单 WorkOrder | 工单创建、分配、处理与状态流转 |
| 资产 Asset | 资产建档、与二维码绑定、批量导入 |
| 巡检 Inspection | 巡检计划制定与巡检记录管理 |
| 组织架构 Department | 部门树、人员与角色（RBAC）管理 |
| 通知 Notification | 站内通知与 Webhook 推送 |
| 工作流 Workflow | 可视化自动化流程引擎 |
| 订阅 Subscription | 套餐与计费管理 |
| 工作台 Workspace | 仪表盘与统一搜索 |
| 开放平台 OpenAPI | API Key + JWT + OAuth2 鉴权，对外集成 |
| 文件管理 File | 上传、下载、预览与文件库 |
| 管理后台 Admin | 用户管理、审计日志、回收站、版本管理等 |

- **国际化**：内置中文 / 英文 / 日文 / 韩文（i18n）
- **权限**：基于角色的访问控制（RBAC）
- **主题**：内置亮色 / 暗色双主题，前端可切换并记忆

---

## 技术栈

- 后端：Python 3.8+ / Flask 2.3 / Flask-CORS
- 数据库：SQLite（默认，可通过环境变量切换路径）
- 前端：原生 HTML + CSS（设计系统 `design-system.css` + 应用样式 `style.css`）+ 原生 JS（`app.js`，全局 CSRF 防护）
- 二维码：qrcode / Pillow / vobject

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. （可选）配置环境变量，见下方「配置」
export SMARTCODE_SECRET_KEY="请替换为随机密钥"
export FLASK_DEBUG=0

# 3. 运行开发服务器
python app.py
# 访问 http://localhost:5000
```

---

## 配置

通过环境变量配置（均带有合理默认值）：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `SMARTCODE_SECRET_KEY` | Flask 会话签名密钥（**生产必须设置**） | 启动时随机生成 |
| `FLASK_DEBUG` | 调试模式（`1` 开启） | `0` |
| `SMARTCODE_DATABASE` | 数据库文件路径 | `data/smartcode.db` |
| `SMARTCODE_UPLOAD_FOLDER` | 上传目录 | `uploads` |
| `SMARTCODE_MAX_FILE_SIZE` | 上传文件大小上限（字节） | `524288000`（500MB） |
| `BASE_URL` | 站点基础地址 | `http://localhost:5000` |

> ⚠️ 生产环境务必设置 `SMARTCODE_SECRET_KEY`，否则会话可被伪造；并设置 `FLASK_DEBUG=0`。

---

## 生产部署

开发服务器（`python app.py`）**不可用于生产**。请使用 WSGI 服务器：

```bash
# Linux / macOS（gunicorn）
gunicorn -w 4 -b 0.0.0.0:5000 "app:app"

# Windows（waitress）
# pip install waitress
waitress-serve --port=5000 app:app
```

反向代理（Nginx）后，将 `SESSION_COOKIE_SECURE` 交由 HTTPS 承载；非本地环境应用会自动启用 `Secure` Cookie。

---

## 目录结构

```
.
├── app.py                 # Flask 应用入口（蓝图注册、CSRF 防护、安全响应头）
├── db_schema.py           # 数据库表初始化
├── requirements.txt       # 依赖清单
├── routes/                # 各功能模块蓝图（auth/qrcode/form/.../admin_*）
├── templates/             # 页面模板（index/home/dashboard/...）
├── static/
│   ├── design-system.css  # 设计系统（token、组件、双主题）
│   ├── style.css          # 应用主样式
│   ├── home.css           # 营销首页样式
│   ├── app.js             # 前端主逻辑（含全局 fetch CSRF 包装）
│   └── csrf.js            # 全局 CSRF Token 注入
├── uploads/               # 用户上传文件（已 gitignore）
└── data/                  # SQLite 数据库（已 gitignore）
```

---

## API 概览

所有业务接口位于 `/api/*`（需登录会话，全站启用 CSRF 防护）；开放平台接口使用 `X-API-Key` 或 `Authorization: Bearer <JWT>` 鉴权，豁免 CSRF。

示例：
- `POST /api/qrcode/...` 二维码生成与管理
- `POST /api/form/...` 表单创建与提交
- `POST /api/workorder/...` 工单操作
- `POST /api/assets` 资产创建（绑定二维码）
- `POST /api/workflow/...` 工作流触发
- `POST /api/open/*` 开放平台接口（API Key / JWT / OAuth2）

> 详细字段以各蓝图路由实现为准。

---

## 安全

- 全站写操作启用 CSRF Token 校验（会话态请求）
- 会话 Cookie 设置 `HttpOnly` + `SameSite=Lax`，非本地 HTTPS 环境启用 `Secure`
- 响应附加 `X-Content-Type-Options` / `X-Frame-Options` / `X-XSS-Protection` 等安全头
- 开放平台通过 API Key / JWT / OAuth2 鉴权，与浏览器会话隔离

---

## License

请依据仓库所属许可使用。
