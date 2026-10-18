# Uses the bundled BuildKit frontend; no separate parser-image pull is needed.
FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
# Keep the npm package cache outside the image layer.  A frontend-only change
# then reuses downloaded packages rather than forcing another network-bound
# dependency install.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit
COPY frontend ./
RUN npm run build

FROM nginx:stable-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
