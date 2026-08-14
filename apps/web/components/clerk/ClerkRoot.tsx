"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { CLERK_PUBLISHABLE_KEY } from "@/lib/auth";

export default function ClerkRoot({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY}>{children}</ClerkProvider>
  );
}
