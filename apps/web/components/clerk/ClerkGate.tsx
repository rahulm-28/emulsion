"use client";

import { SignIn, SignedIn, SignedOut } from "@clerk/nextjs";
import { LogIn } from "lucide-react";
import { LogoMark } from "../Logo";

/** Everything that touches the Clerk SDK lives behind this module boundary. */
export default function ClerkGate({
  children,
}: {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut>
        <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-8 px-6">
          <div className="text-center">
            <LogoMark className="mx-auto size-9 text-accent-fill" />
            <h1 className="mt-5 font-serif text-[32px] leading-tight tracking-tight">
              Emulsion
            </h1>
            <p className="mt-2 flex items-center justify-center gap-1.5 text-[13px] text-muted-foreground">
              <LogIn className="size-3.5" />
              Sign in to keep your conversations and images
            </p>
          </div>
          <SignIn routing="hash" />
        </div>
      </SignedOut>
    </>
  );
}
