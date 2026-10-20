FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY m2a ./m2a
COPY memory ./memory
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT', '8080') + '/health')"
# PORT is set by hosts like Railway; 8080 for local Docker/Terraform.
CMD ["sh", "-c", "uvicorn m2a.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
