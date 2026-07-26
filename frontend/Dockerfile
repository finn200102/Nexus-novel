# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
# Keep the npm package cache outside the image layer.  A frontend-only change
# then reuses downloaded packages rather than forcing another network-bound
# dependency install.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit
COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
