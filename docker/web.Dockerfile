# ── base: pnpm + node ───────────────────────────────────────────
FROM node:20-alpine AS base
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

# ── deps: fetch all packages to store ──────────────────────────
FROM base AS deps
WORKDIR /app
COPY pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm fetch

# ── build: install + compile ───────────────────────────────────
FROM deps AS build
WORKDIR /app
COPY . .
RUN pnpm install -r --offline
ENV NEXT_OUTPUT=standalone
# NEXT_PUBLIC_* vars are inlined into the client bundle at BUILD time, so
# they can't be set at runtime via `environment:`. Value comes from the
# compose build-arg below (defaults to the dev gateway); the production
# deploy sets NEXT_PUBLIC_API_URL in .env (e.g. https://dt.example.com).
ARG NEXT_PUBLIC_API_URL=http://localhost:4000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN pnpm --filter @digital-twin-fm/web run build

# ── runner: minimal production image ───────────────────────────
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# Next.js standalone output (monorepo layout preserved)
COPY --from=build /app/apps/web/.next/standalone ./

# Static assets are served from .next/static (not bundled in standalone)
COPY --from=build /app/apps/web/.next/static ./apps/web/.next/static

EXPOSE 3000
CMD ["node", "apps/web/server.js"]
