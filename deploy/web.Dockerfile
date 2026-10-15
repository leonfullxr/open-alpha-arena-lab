FROM node:22.14.0-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27.4-alpine
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /src/dist/web /usr/share/nginx/html
EXPOSE 8080
