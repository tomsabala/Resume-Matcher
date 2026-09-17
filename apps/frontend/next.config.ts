import type { NextConfig } from 'next';

const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000';

// Request timeout (ms) for the API proxy. MUST match the backend's
// REQUEST_TIMEOUT_SECONDS and the client AbortController (lib/api/client.ts) —
// the shortest layer aborts first, so all three are driven by the same
// NEXT_PUBLIC_REQUEST_TIMEOUT_MS env var. Bounded to [30s, 30min].
const rawTimeoutMs = process.env.NEXT_PUBLIC_REQUEST_TIMEOUT_MS;
const parsedTimeoutMs = rawTimeoutMs ? Number(rawTimeoutMs) : NaN;
const REQUEST_TIMEOUT_MS = Number.isFinite(parsedTimeoutMs)
  ? Math.min(1_800_000, Math.max(30_000, parsedTimeoutMs))
  : 240_000;

// Mount path when the app is served under a prefix (e.g. /a/resume-matcher behind a
// gateway). Inlined at build time, so the value is baked into the image. Next prefixes its
// own routes, /_next/*, and the `rewrites()` sources below, so a browser request to
// `<base>/api/v1/...` still reaches `${BACKEND_ORIGIN}/api/v1/...`.
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? '').replace(/\/+$/, '');

const nextConfig: NextConfig = {
  output: 'standalone',
  basePath: BASE_PATH || undefined,
  experimental: {
    proxyTimeout: REQUEST_TIMEOUT_MS,
    // Tree-shake barrel imports — saves ~200-800ms cold start per route
    optimizePackageImports: [
      'lucide-react',
      '@tiptap/react',
      '@tiptap/starter-kit',
      '@tiptap/extension-link',
      '@tiptap/extension-underline',
      '@dnd-kit/core',
      '@dnd-kit/sortable',
      '@dnd-kit/utilities',
    ],
  },
  async rewrites() {
    // Note: Next.js serves filesystem routes (app/api/) before rewrites.
    // Do not create app/api/ routes or they will shadow the backend proxy.
    return [
      {
        source: '/api/:path*',
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
      {
        source: '/docs',
        destination: `${BACKEND_ORIGIN}/docs`,
      },
      {
        source: '/redoc',
        destination: `${BACKEND_ORIGIN}/redoc`,
      },
      {
        source: '/openapi.json',
        destination: `${BACKEND_ORIGIN}/openapi.json`,
      },
    ];
  },
};

export default nextConfig;
