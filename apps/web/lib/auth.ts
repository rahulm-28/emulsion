/**
 * Whether sign-in is switched on, and how the client gets a token.
 *
 * Auth is opt-in by configuration. With no Clerk key present the app runs exactly as it
 * did before — one implicit local user, no accounts, no network — which is what keeps
 * `make dev` working with nothing installed. Setting the key turns on the whole flow
 * without touching any other file.
 *
 * `NEXT_PUBLIC_*` is inlined at build time, so this is a constant in the bundle rather
 * than a runtime lookup.
 */
export const CLERK_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";

export const authEnabled = CLERK_PUBLISHABLE_KEY.length > 0;

/**
 * Attach the session token to an API call.
 *
 * Clerk also sets a `__session` cookie on this origin, and the API accepts it — which is
 * how `EventSource` authenticates, since it cannot set headers. The explicit header is
 * still sent for ordinary fetches because it survives stricter cookie policies.
 */
export async function authHeaders(): Promise<Record<string, string>> {
  if (!authEnabled) return {};
  if (typeof window === "undefined") return {};

  // Clerk attaches this to the window once loaded. Reading it lazily keeps this module
  // free of a hard dependency on the SDK, so the no-auth build does not pull it in.
  const clerk = (window as unknown as { Clerk?: { session?: { getToken(): Promise<string | null> } } })
    .Clerk;
  const token = await clerk?.session?.getToken().catch(() => null);
  return token ? { Authorization: `Bearer ${token}` } : {};
}
