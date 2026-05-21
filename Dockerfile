FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1

WORKDIR /app

RUN python -m pip install --upgrade pip

COPY online_app/requirements.txt /app/online_app/requirements.txt
RUN pip install --no-cache-dir -r /app/online_app/requirements.txt

COPY . /app

CMD ["sh", "-c", "uvicorn online_app.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
