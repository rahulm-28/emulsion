"use client";

import dynamic from "next/dynamic";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { authEnabled } from "@/lib/auth";

// Loaded as its own chunk, and only when a key is configured.
const ClerkRoot = dynamic(() => import("@/components/clerk/ClerkRoot"), { ssr: false });

export function Providers({ children }: { children: React.ReactNode }) {
  const inner = (
    <TooltipProvider delayDuration={350} skipDelayDuration={200}>
      {children}
    </TooltipProvider>
  );

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {/* Inside ThemeProvider, not outside it: ClerkRoot reads the resolved theme so
          Clerk's own components match the app in both light and dark. */}
      {authEnabled ? <ClerkRoot>{inner}</ClerkRoot> : inner}
    </ThemeProvider>
  );
}
