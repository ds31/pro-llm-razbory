# Образ агента: API и воркер — один образ, разные команды. Зависимостей нет — только стандартная библиотека.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app
COPY src ./src
# не root: процессу агента не нужны права на систему
RUN useradd --create-home --uid 10001 agent && mkdir -p /data && chown agent /data
USER agent
ENTRYPOINT ["python", "-m", "razbor07"]
