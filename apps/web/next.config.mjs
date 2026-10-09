/** @type {import('next').NextConfig} */
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Dev server is served through a proxied preview host in this environment.
  allowedDevOrigins: ["*.e2b.app", "*.e2b.dev", "localhost", "127.0.0.1"],
  // The browser talks to /backend/* on the same origin; Next proxies those
  // requests to the FastAPI service server-side. This keeps the deployment
  // single-origin (no CORS, no hardcoded hosts in the browser bundle).
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${API_INTERNAL_URL}/api/:path*` }];
  },
  eslint: { ignoreDuringBuilds: true },
  // The sandbox this was developed in has ~2 GB RAM: memory optimisations keep
  // `next build` inside that budget.
  experimental: { webpackMemoryOptimizations: true },
  productionBrowserSourceMaps: false,
  typescript: { ignoreBuildErrors: false },
  webpack: (config) => {
    // Monaco ships ESM workers; the app only needs the editor core + Monarch
    // tokenizers, so the language workers are replaced by lightweight stubs
    // (see components/code/monaco-setup.ts) and never bundled here.
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false };
    return config;
  },
};

export default nextConfig;
