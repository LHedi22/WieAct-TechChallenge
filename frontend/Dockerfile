# Build context is the repo root (docker-compose.yml): the theme reads ../design/tokens.json.
FROM node:22-slim
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
COPY design/tokens.json /design/tokens.json
COPY design/assets /design/assets
EXPOSE 5173
CMD ["pnpm", "dev", "--host"]
