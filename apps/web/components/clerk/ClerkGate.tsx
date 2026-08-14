"use client";

import { RedirectToSignIn, Show } from "@clerk/nextjs";

/**
 * Everything that touches the Clerk SDK lives behind this module boundary.
 *
 * `Show` rather than `SignedIn`/`SignedOut`: @clerk/nextjs v7 is Core 3, where those
 * two are shims that throw at runtime.
 *
 * Signed-out visitors are redirected to /sign-in rather than shown a form inline, so
 * there is exactly one sign-in surface and Clerk's own "create account" link resolves
 * to the real /sign-up route instead of dead-ending.
 */
export default function ClerkGate({
  children,
}: {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  return (
    <>
      <Show when="signed-in">{children}</Show>
      <Show when="signed-out">
        <RedirectToSignIn />
      </Show>
    </>
  );
}
