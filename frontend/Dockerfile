# Build context is the repo root (docker-compose.yml): the theme reads ../design/tokens.json.
FROM node:22-slim
# Some networks block registry.npmjs.org by hostname; NPM_REGISTRY=https://registry.yarnpkg.com/
# (same registry, same integrity hashes) works around it. Used for pnpm itself and the packages.
ARG NPM_REGISTRY=https://registry.npmjs.org/
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    COREPACK_NPM_REGISTRY=${NPM_REGISTRY} \
    npm_config_registry=${NPM_REGISTRY}
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
COPY design/tokens.json /design/tokens.json
COPY design/assets /design/assets
EXPOSE 5173
CMD ["pnpm", "dev", "--host"]
