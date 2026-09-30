FROM node:24.15.0-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29.3-alpine

ENV MCP_UPSTREAM=http://mcp:8000/mcp \
    NGINX_ENVSUBST_FILTER=MCP_UPSTREAM
COPY nginx/templates/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
