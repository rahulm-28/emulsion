/**
 * The browser only ever talks to this origin.
 *
 * That mirrors production exactly: Front Door path-routes /v1/* and /_blobs/* to the
 * API and everything else to Next (M0 §3). Same-origin in dev means no CORS, no
 * split-cookie problems, and no per-environment API base URL in the client code.
 */
const API_ORIGIN = process.env.EMULSION_API_ORIGIN ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Next 15 also clones bodies for external rewrites, even when middleware is
  // excluded. Its 10 MB default would truncate valid large image uploads.
  experimental: { middlewareClientMaxBodySize: "50mb" },
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${API_ORIGIN}/v1/:path*` },
      { source: "/_blobs/:path*", destination: `${API_ORIGIN}/_blobs/:path*` },
      { source: "/_uploads/:path*", destination: `${API_ORIGIN}/_uploads/:path*` },
      { source: "/health", destination: `${API_ORIGIN}/health` },
    ];
  },
};

export default nextConfig;
