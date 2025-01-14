FROM python:3.9-slim
WORKDIR /app
COPY app/ /app/
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Run the Flask app with Gunicorn using the PORT environment variable
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:4499 turnify:app"]
