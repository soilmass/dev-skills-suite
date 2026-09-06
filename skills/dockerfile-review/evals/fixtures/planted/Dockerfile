FROM node:latest
ARG NPM_TOKEN
COPY . .
RUN npm ci
RUN apt-get install -y curl
ADD ./src /app/src
RUN npm run build
EXPOSE 3000
