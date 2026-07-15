# ASEP web — production image. Next.js standalone output: the runtime stage
# carries only the built server, not the monorepo. Build from the repo root:
#   docker build -f infra/docker/web.Dockerfile -t asep-web .
# Design note: docs/architecture/KUBERNETES_DEPLOY.md

FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo

# Manifests first so dependency layers cache across source edits.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json apps/web/
COPY packages/shared/package.json packages/shared/
RUN pnpm install --frozen-lockfile --filter web...

COPY apps/web apps/web
COPY packages/shared packages/shared
RUN pnpm --filter web build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production

# Standalone output keeps the monorepo layout: the server entry lands at
# apps/web/server.js, with its pruned node_modules alongside.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static

USER node
EXPOSE 3000
ENV HOSTNAME=0.0.0.0 PORT=3000
CMD ["node", "apps/web/server.js"]
