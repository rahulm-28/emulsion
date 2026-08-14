"use client";

import dynamic from "next/dynamic";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { authEnabled } from "@/lib/auth";

const ClerkRoot = dynamic(() => import("@/components/clerk/ClerkRoot"), { ssr: false });

export function Providers({ children }: { children: React.ReactNode }) {
  const tree = (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <TooltipProvider delayDuration={350} skipDelayDuration={200}>
        {children}
      </TooltipProvider>
    </ThemeProvider>
  );
  // Loaded as its own chunk, and only when a key is configured.
  return authEnabled ? <ClerkRoot>{tree}</ClerkRoot> : tree;
}
