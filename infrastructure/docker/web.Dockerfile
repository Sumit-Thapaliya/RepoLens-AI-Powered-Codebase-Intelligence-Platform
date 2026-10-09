# ---------------------------------------------------------------------------
# RepoLens web image - Next.js (standalone output), API proxied server-side
# ---------------------------------------------------------------------------
FROM node:20-alpine AS deps
WORKDIR /srv/web
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /srv/web
ARG NEXT_PUBLIC_API_BASE=/backend
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_OPTIONS=--max-old-space-size=2048
COPY --from=deps /srv/web/node_modules ./node_modules
COPY apps/web ./
# `output: standalone` is enabled through this env flag so local dev is unaffected.
ENV REPOLENS_DOCKER_BUILD=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /srv/web
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    API_INTERNAL_URL=http://api:8000
RUN addgroup -g 10001 -S repolens && adduser -S -u 10001 -G repolens repolens
COPY --from=builder --chown=repolens:repolens /srv/web/public ./public
COPY --from=builder --chown=repolens:repolens /srv/web/.next/standalone ./
COPY --from=builder --chown=repolens:repolens /srv/web/.next/static ./.next/static
USER repolens
EXPOSE 3000
CMD ["node", "server.js"]
