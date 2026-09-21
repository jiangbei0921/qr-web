"""
智码云（SmartCode）二维码生成器
Python Flask 实现

安装依赖包：
pip install flask flask-cors pillow qrcode python-vobject

项目结构：
.
├── app.py                  # Flask 后端应用
├── requirements.txt        # 依赖包列表
├── templates/
│   └── index.html         # HTML 前端页面
├── static/
│   ├── style.css          # 样式表
│   └── app.js             # 前端交互脚本
└── uploads/               # 上传文件目录

运行应用：
python app.py

访问地址：
http://localhost:5000

功能特性：
1. 单个二维码生成 - 支持多种类型
2. 批量生成 - CSV 文件导入
3. 美化设置 - 颜色、样式、Logo
4. 多种格式 - PNG、SVG 导出
5. 历史记录 - 本地存储查询
6. 生成统计 - 实时统计数据

支持的二维码类型：
- 文本 (Text)
- 网址 (URL)
- 邮件 (Email)
- 短信 (SMS)
- 名片 (vCard)
- WiFi 连接

美化选项：
- 样式选择 (方形/圆角)
- 前景色设置
- 背景色设置
- 二维码尺寸调整
- 容错率选择
- Logo 嵌入
- 颜色梯度

API 端点：
POST /api/generate          - 生成单个二维码
POST /api/generate_batch    - 批量生成
POST /api/upload_logo       - 上传 Logo
POST /api/download          - 下载二维码
POST /api/export_svg        - 导出 SVG
GET  /api/stats             - 获取统计数据
GET  /api/templates         - 获取模板列表
"""

# 依赖包版本要求
"""
Flask==2.3.0
Flask-CORS==4.0.0
Pillow==10.0.0
qrcode==7.4.2
python-vobject==0.9.6.1
Werkzeug==2.3.0
"""
