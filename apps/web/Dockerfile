FROM node:20-alpine AS base
RUN npm install -g pnpm@9

FROM base AS deps
WORKDIR /app
COPY apps/web/package.json ./package.json
RUN pnpm install --no-frozen-lockfile

FROM base AS development
WORKDIR /app
COPY --from=deps /app/node_modules node_modules
COPY apps/web .
CMD ["pnpm", "dev"]

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules node_modules
COPY apps/web .
RUN mkdir -p public && pnpm build

FROM node:20-alpine AS runner
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static .next/static
COPY --from=builder /app/public public
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD wget -qO- http://localhost:3000/ || exit 1
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]
