FROM node:22-alpine AS base
RUN npm install -g pnpm@9

FROM base AS deps
WORKDIR /app
# Copy workspace manifests so pnpm resolves overrides correctly
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/
RUN pnpm install --frozen-lockfile --filter @lex-agents/web

FROM base AS builder
WORKDIR /app
# Workspace manifests needed for Turbopack root detection in Next.js 16
COPY package.json pnpm-workspace.yaml ./
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY apps/web ./apps/web
WORKDIR /app/apps/web
RUN pnpm build

FROM node:22-alpine AS runner
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/apps/web/.next/standalone ./
COPY --from=builder /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /app/apps/web/public ./apps/web/public
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
  CMD ["node", "-e", "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<400?0:1)).on('error',()=>process.exit(1))"]
USER nextjs
EXPOSE 3000
# PORT is read by Next.js standalone server.js.
# HOSTNAME: Docker/ECS overrides this with the container's EC2 hostname; we force it
# back to 0.0.0.0 via the CMD wrapper so Next.js listens on all interfaces.
ENV PORT=3000
WORKDIR /app/apps/web
# Use shell wrapper to force HOSTNAME=0.0.0.0 regardless of what Docker injected.
CMD ["/bin/sh", "-c", "HOSTNAME=0.0.0.0 exec node server.js"]
