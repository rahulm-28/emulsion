"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { useTheme } from "next-themes";
import { CLERK_PUBLISHABLE_KEY } from "@/lib/auth";

/**
 * Clerk's components, wearing this app's palette.
 *
 * Without this they render in Clerk's own light theme, which means a white card on a
 * near-black page for every dark-mode visitor — the sign-in screen is the first thing a
 * new user ever sees, so it is the worst possible place to look bolted on.
 *
 * Concrete hex rather than `var(--card)`: Clerk derives hover, focus and alpha variants
 * from these values, and it cannot do arithmetic on a CSS variable it never resolves.
 * The two palettes below are the same tokens as globals.css.
 */
const LIGHT = {
  colorBackground: "#ffffff",
  colorForeground: "#101012",
  colorText: "#101012",
  colorMutedForeground: "#4d4d57",
  colorTextSecondary: "#4d4d57",
  colorPrimary: "#101012",
  colorPrimaryForeground: "#fbfbfc",
  colorInput: "#ffffff",
  colorInputBackground: "#ffffff",
  colorInputForeground: "#101012",
  colorInputText: "#101012",
  colorBorder: "#e8e8ec",
  colorRing: "#101012",
  colorDanger: "#be2a2a",
  colorSuccess: "#15803d",
  colorNeutral: "#101012",
};

const DARK = {
  colorBackground: "#101013",
  colorForeground: "#f4f4f6",
  colorText: "#f4f4f6",
  colorMutedForeground: "#a2a2ac",
  colorTextSecondary: "#a2a2ac",
  colorPrimary: "#f4f4f6",
  colorPrimaryForeground: "#0a0a0c",
  colorInput: "#17171b",
  colorInputBackground: "#17171b",
  colorInputForeground: "#f4f4f6",
  colorInputText: "#f4f4f6",
  colorBorder: "#212127",
  colorRing: "#e0a93f",
  colorDanger: "#f87171",
  colorSuccess: "#4ade80",
  colorNeutral: "#f4f4f6",
};

export default function ClerkRoot({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme();

  return (
    <ClerkProvider
      publishableKey={CLERK_PUBLISHABLE_KEY}
      afterSignOutUrl="/sign-in"
      appearance={{
        variables: {
          ...(resolvedTheme === "dark" ? DARK : LIGHT),
          fontFamily: "var(--font-sans)",
          borderRadius: "0.75rem",
        },
        elements: {
          cardBox: { boxShadow: "none", border: "1px solid var(--border)" },
          card: { boxShadow: "none" },
          // Clerk's own footer badge duplicates chrome the app already has.
          footerActionLink: { color: "var(--accent)" },
        },
      }}
    >
      {children}
    </ClerkProvider>
  );
}
