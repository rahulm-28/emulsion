/**
 * The mark: three offset layers — the coated emulsion. Outlined rather than filled so
 * the three-layer read survives down to 16px, with the front layer washed in accent.
 */
export function LogoMark({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
        <rect x="13" y="4.6" width="14.4" height="14.4" rx="4" opacity="0.28" />
        <rect x="9.5" y="8.1" width="14.4" height="14.4" rx="4" opacity="0.55" />
        <rect
          x="6"
          y="11.6"
          width="14.4"
          height="14.4"
          rx="4"
          fill="currentColor"
          fillOpacity="0.13"
        />
      </g>
    </svg>
  );
}

export function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark className="size-[26px] text-accent-fill" />
      <span className="font-serif text-[19px] leading-none tracking-tight text-foreground">
        Emulsion
      </span>
    </div>
  );
}
