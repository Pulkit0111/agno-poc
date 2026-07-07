# Bott Console — the Next.js admin/ops web app.
# Build (from repo root):  docker build -t bott-console -f console/Dockerfile console
# Run:    docker run -p 3000:3000 -e BOTT_API_ORIGIN=http://bott-app:7777 bott-console
#
# BOTT_API_ORIGIN must point at wherever the Python backend (Dockerfile at the repo root)
# actually runs — next.config.ts rewrites /api/* there. In a docker-compose/k8s setup,
# that's the backend service's internal hostname, not localhost.

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.ts ./next.config.ts

EXPOSE 3000
CMD ["npm", "run", "start"]
