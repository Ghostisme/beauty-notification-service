FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOOL_DATA_DIR=/app/data TOOL_HOST=0.0.0.0 TOOL_PORT=8790
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin laike
COPY toolbox ./toolbox
COPY run.py manage.py ./
USER 10001:10001
EXPOSE 8790
CMD ["python", "run.py"]
