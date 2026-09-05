FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
COPY . .

# v4.37: Security hardening — non-root user
RUN groupadd -r gwuser && useradd -r -g gwuser -s /sbin/nologin gwuser \
    && chown -R gwuser:gwuser /app
USER gwuser

EXPOSE 8100
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100"]
