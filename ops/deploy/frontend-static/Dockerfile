FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=https://gabi-dou-web.fly.dev/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY src/frontend/web/package.json src/frontend/web/package-lock.json ./src/frontend/web/
WORKDIR /app/src/frontend/web
RUN npm ci

COPY src/frontend/web/ /app/src/frontend/web/
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine

COPY ops/deploy/frontend-static/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/src/frontend/web/dist /usr/share/nginx/html

EXPOSE 8080
