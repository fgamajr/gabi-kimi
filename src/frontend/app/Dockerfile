FROM node:20-alpine

WORKDIR /app

COPY src/frontend/app/package*.json ./
RUN npm ci

COPY src/frontend/app/ ./

ENV VITE_API_PROXY_TARGET=http://backend:8000

EXPOSE 8080

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "8080"]
