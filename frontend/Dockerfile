# Frontend: build the Vite app, serve the static output with nginx.
#
# VITE_API_BASE is a *build-time* value — Vite inlines `import.meta.env.*`
# into the JS bundle at build, not at container start. Pass it as a build arg
# pointing at the backend service's public URL:
#   docker build --build-arg VITE_API_BASE=https://your-backend.up.railway.app .
# On Railway, set VITE_API_BASE as a variable on this service; Railway passes
# service variables through as build args automatically.

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_API_BASE
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Railway injects $PORT; nginx's docker-entrypoint envsubst's *.template
# files in /etc/nginx/templates into /etc/nginx/conf.d on container start.
ENV PORT=8080
EXPOSE 8080
