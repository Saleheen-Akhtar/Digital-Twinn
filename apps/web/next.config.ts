import type { NextConfig } from 'next';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const withBundleAnalyzer =
  process.env.ANALYZE === 'true'
    ? require('@next/bundle-analyzer')({ enabled: true })
    : (cfg: NextConfig) => cfg;

// Load monorepo-root `.env` into `process.env` BEFORE Next.js boots the
// server, so the middleware (which reads `process.env.JWT_ACCESS_SECRET`
// lazily on every request) sees the secret.
//
// Why this is needed: `next dev` (started by turbo under `pnpm dev`) runs
// with `cwd = apps/web`. Next.js's built-in `.env` loader looks for
// `.env` in cwd only, so it never finds the monorepo-root `.env` and the
// web middleware ends up running with an empty `process.env` — which
// breaks JWT verification (mirrors the api-gateway's loader bug
// fixed in `apps/api-gateway/src/config/infisical.loader.ts`).
//
// We use the same walk-up `findMonorepoRoot` pattern as the api-gateway
// loader, kept inline to avoid a new shared package for two callsites.
// `next.config.ts` runs once at server boot, in the Node runtime, with
// full `fs` / `path` access — so there's no edge-bundle issue like with
// `instrumentation.ts`.
function findMonorepoRoot(startDir: string): string {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require('fs') as {
    existsSync: (p: string) => boolean;
    statSync: (p: string) => { isFile: () => boolean };
  };
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require('path') as { resolve: (...parts: string[]) => string };
  let dir = path.resolve(startDir);
  for (let i = 0; i < 16; i++) {
    if (
      fs.existsSync(path.resolve(dir, 'pnpm-workspace.yaml')) ||
      fs.existsSync(path.resolve(dir, 'turbo.json'))
    ) {
      return dir;
    }
    const pkgPath = path.resolve(dir, 'package.json');
    if (fs.existsSync(pkgPath) && fs.statSync(pkgPath).isFile()) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const pkg = require(pkgPath) as { workspaces?: unknown };
        if (pkg.workspaces) return dir;
      } catch {
        /* not fatal */
      }
    }
    const parent = path.resolve(dir, '..');
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(startDir);
}

function loadMonorepoEnv(): void {
  // Production: rely on orchestrator-injected secrets (k8s, ECS, etc.).
  if (process.env.NODE_ENV === 'production') return;

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require('fs') as { existsSync: (p: string) => boolean };
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require('path') as { resolve: (...parts: string[]) => string };
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const dotenv = require('dotenv') as {
    config: (opts: { path: string; override: boolean }) => { error?: Error };
  };

  const root = findMonorepoRoot(process.cwd());
  const candidates = [
    path.resolve(process.cwd(), '.env'), // service-local override wins
    path.resolve(root, '.env'), // shared monorepo fallback
  ];
  for (const envPath of candidates) {
    if (!fs.existsSync(envPath)) continue;
    const r = dotenv.config({ path: envPath, override: false });
    if (r.error) {
      // eslint-disable-next-line no-console
      console.warn(`[next.config] failed to load ${envPath}`);
      return;
    }
    // eslint-disable-next-line no-console
    console.log(`[next.config] loaded ${envPath}`);
    return;
  }
  // eslint-disable-next-line no-console
  console.warn(
    `[next.config] no .env found in ${candidates.join(' or ')}; ` +
      'relying on process.env (production / orchestrator-injected secrets path).',
  );
}

loadMonorepoEnv();

const isDev = process.env.NODE_ENV !== 'production';

const csp = [
  "default-src 'self'",
  // Next.js fast refresh requires unsafe-eval in development + blob: for HMR
  `script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  // Allow connecting to the api gateway (internal DNS in Docker, localhost in dev),
  // websockets for realtime, and blob: for 3D textures
  `connect-src 'self' blob: ws: http://api-gateway:4000 http://localhost:4000 http://127.0.0.1:4000 ws://localhost:4000 ws://localhost:3000`,
  "worker-src 'self' blob:",
  "child-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ');

const securityHeaders = [
  { key: 'Content-Security-Policy', value: csp },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()' },
  { key: 'X-DNS-Prefetch-Control', value: 'off' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
];

const analyzerEnabled = process.env.ANALYZE === 'true';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@digital-twin-fm/db'],
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: false },
  async headers() {
    return [{ source: '/(.*)', headers: securityHeaders }];
  },
};

export default analyzerEnabled ? withBundleAnalyzer(nextConfig) : nextConfig;
