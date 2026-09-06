FROM python:3.12@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
WORKDIR /app
COPY requirements.txt .
COPY app.py .
USER app
EXPOSE 8000
