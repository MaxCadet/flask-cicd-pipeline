FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir flask==3.0.0

COPY app/ .

EXPOSE 5000

CMD ["python", "app.py"]