// Three-lamp traffic light mark; the lit lamp is the AI green.
export function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-9 w-9 shrink-0" aria-hidden>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="#0b1c3e" />
      <rect x="11" y="5" width="10" height="22" rx="5" fill="#1d3663" />
      <circle cx="16" cy="10" r="2.6" fill="#ff5c52" opacity="0.35" />
      <circle cx="16" cy="16" r="2.6" fill="#ffab2e" opacity="0.35" />
      <circle cx="16" cy="22" r="2.6" fill="#32d17a" />
    </svg>
  );
}
