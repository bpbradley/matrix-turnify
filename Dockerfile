FROM python:3.10-slim

WORKDIR /app

COPY app/ /app/

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production
ENV LOG_LEVEL=info

CMD ["sh", "-c", "gunicorn -b 0.0.0.0:4499 turnify:app \
    --log-level $(echo $LOG_LEVEL | tr '[:upper:]' '[:lower:]') \
    --access-logfile ${GUNICORN_ACCESS_LOG:-'-'} \
    --error-logfile ${GUNICORN_ERROR_LOG:-'-'}"]