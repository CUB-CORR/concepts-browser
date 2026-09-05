# SvelteKit (adapter-node) production image. Build with the full toolchain, then ship the
# compiled `build/` output on a lean runtime. Build context is ./app (see docker-compose).
FROM node:24-slim AS build

# NODE_USE_ENV_PROXY (Node 24+) makes Node's global fetch honour http(s)_proxy/no_proxy env
# vars if set — a no-op otherwise. Behind a corporate proxy, pass Docker's predefined
# HTTP_PROXY/HTTPS_PROXY/NO_PROXY build args via a compose override; no ARG needed here.
ENV NODE_USE_ENV_PROXY=1

WORKDIR /app
RUN corepack enable

# Install deps against the lockfile first (better layer caching).
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build
# adapter-node bundles devDependencies into build/ and leaves `dependencies` external, so
# only the latter need to exist at runtime. monaco-editor is a *build-time* dep listed under
# `dependencies` purely to keep it out of the server bundle (it is browser-only, and rollup
# chokes on its CSS) — the server never imports it, so drop its 73 MB from the runtime image.
RUN pnpm prune --prod && rm -rf node_modules/monaco-editor node_modules/.pnpm/monaco-editor*

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production
# ORIGIN lets adapter-node accept form POSTs (e.g. /login) behind a proxy; override per env.
ENV ORIGIN=http://localhost:3000
# Node's global fetch ignores http(s)_proxy by default, so server-side fetch (e.g. the Notion
# SDK) can't reach external APIs from behind a corporate proxy. NODE_USE_ENV_PROXY=1 (Node 24+)
# makes fetch honour http(s)_proxy/no_proxy env vars when the deployment sets them — remember
# no_proxy=localhost,api so internal traffic stays direct.
ENV NODE_USE_ENV_PROXY=1
# Commit this image was built from, shown in the page footer so a deployment can tell which
# release is live. Read at runtime (adapter-node + $env/dynamic/public), so baking it in here
# needs no rebuild of the JS; empty ⇒ nothing is rendered. CI passes --build-arg.
ARG PUBLIC_BUILD_COMMIT=""
ENV PUBLIC_BUILD_COMMIT=$PUBLIC_BUILD_COMMIT
COPY --from=build /app/build ./build
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
EXPOSE 3000
CMD ["node", "build"]
