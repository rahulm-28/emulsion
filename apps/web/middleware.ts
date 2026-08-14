import { clerkMiddleware } from "@clerk/nextjs/server";

export default clerkMiddleware();

export const config = {
  matcher: [
    /*
     * Everything except Next internals, static assets, and the three paths
     * next.config.mjs rewrites straight through to FastAPI.
     *
     * Excluding /v1, /_blobs and /health is not an optimisation. Those are a reverse
     * proxy to another service, and one of them — /v1/jobs/:id/events — is a
     * long-lived SSE stream that must not pass through an edge handler that can
     * buffer it. Authorisation on those paths is the API's job, and it already
     * scopes every route by owner.
     */
    "/((?!_next|v1/|_blobs/|health|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    // Clerk's auto-proxy, so the browser talks to this origin rather than a
    // clerk.accounts.dev subdomain.
    "/__clerk/:path*",
  ],
};
