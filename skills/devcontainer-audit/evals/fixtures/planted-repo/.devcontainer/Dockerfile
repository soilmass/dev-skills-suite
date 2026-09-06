# Planted Dockerfile: every pattern
FROM python
ARG NPM_TOKEN
RUN apt-get update && apt-get install -y git
COPY . /app
RUN pip install -e /app
