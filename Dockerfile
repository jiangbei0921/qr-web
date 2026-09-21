# 智码云 SmartCode 生产镜像
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# 优先安装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

EXPOSE 8000

# 通过 gunicorn.conf.py 读取 PORT / WEB_CONCURRENCY 环境变量
CMD ["sh", "-c", "gunicorn -c gunicorn.conf.py app:app"]
