type Tone = "ok" | "off" | "alert" | "warn" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "bg-ai/10 text-ai border-ai/25",
  off: "bg-muted text-muted-foreground border-border",
  alert: "bg-fix text-white border-fix pulse-red",
  warn: "bg-rush/10 text-rush border-rush/30",
  neutral: "bg-white/70 text-foreground border-border",
};

export function Pill({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-semibold whitespace-nowrap ${TONES[tone]}`}>
      {(tone === "ok" || tone === "alert") && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      <span className="font-medium opacity-70">{label}</span>
      {value}
    </span>
  );
}
