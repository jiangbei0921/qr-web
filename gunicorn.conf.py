# gunicorn 生产配置
# 读取环境变量 PORT / WEB_CONCURRENCY，缺省使用 8000 / 4
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get('WEB_CONCURRENCY', '4'))
worker_class = 'sync'
timeout = 120
keepalive = 5
accesslog = '-'
errorlog = '-'
loglevel = 'info'
