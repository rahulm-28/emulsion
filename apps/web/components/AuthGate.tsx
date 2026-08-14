"use client";

import dynamic from "next/dynamic";
import { LogIn } from "lucide-react";
import { authEnabled } from "@/lib/auth";
import { LogoMark } from "./Logo";

/**
 * Sign-in, but only when sign-in exists.
 *
 * With no Clerk key configured this renders its children untouched — the app is
 * single-user local mode and there is nothing to sign in to. That is what keeps the
 * "runs on your machine with no cloud account" promise true while the same build also
 * ships accounts.
 *
 * The Clerk pieces load through `next/dynamic`, so they land in their own chunk rather
 * than the initial bundle. A plain conditional `require()` does not achieve this —
 * webpack keeps the module even on a branch that never runs, which cost 100 kB of
 * First Load JS before this was measured.
 */
const ClerkGate = dynamic(() => import("./clerk/ClerkGate"), { ssr: false });

export function AuthGate({ children }: { children: React.ReactNode }) {
  if (!authEnabled) return <>{children}</>;
  return (
    <ClerkGate
      fallback={
        <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 px-6 text-center">
          <LogoMark className="size-9 text-accent-fill" />
          <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <LogIn className="size-3.5" />
            Preparing sign-in…
          </p>
        </div>
      }
    >
      {children}
    </ClerkGate>
  );
}
