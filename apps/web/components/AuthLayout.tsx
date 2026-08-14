import { LogoMark } from "./Logo";

/** Shared chrome for /sign-in and /sign-up, so both read as part of the app. */
export function AuthLayout({
  caption,
  children,
}: {
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-8 px-6">
      <div className="text-center">
        <LogoMark className="mx-auto size-9 text-accent-fill" />
        <h1 className="mt-5 font-serif text-[32px] leading-tight tracking-tight">
          Emulsion
        </h1>
        <p className="mt-2 text-[13px] text-muted-foreground">{caption}</p>
      </div>
      {children}
    </main>
  );
}
