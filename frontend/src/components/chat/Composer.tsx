import { useRef, useEffect } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [value]);

  return (
    <div className="rounded-[14px] border border-[var(--color-line)] bg-[var(--color-surface)] p-2 shadow-[var(--shadow-soft)]">
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          value={value}
          rows={1}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!streaming) onSend();
            }
          }}
          placeholder="Ask about properties, projects, prices, or what a source says…"
          className="max-h-[180px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-[var(--color-ink-soft)]"
          aria-label="Message"
        />
        {streaming ? (
          <Button size="icon" variant="subtle" onClick={onStop} aria-label="Stop generating">
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={onSend}
            disabled={disabled || !value.trim()}
            aria-label="Send message"
          >
            <ArrowUp />
          </Button>
        )}
      </div>
      <p className="px-2 pt-1 text-[11px] text-[var(--color-ink-soft)]">
        Enter to send · Shift+Enter for a new line. Answers are grounded in collected DarGlobal &
        Wasalt pages.
      </p>
    </div>
  );
}
