import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[14px] border border-[var(--color-line)] bg-[var(--color-surface)]",
        className,
      )}
      {...p}
    />
  );
}

export function Badge({
  className,
  tone = "neutral",
  ...p
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "accent" | "warm" | "muted" }) {
  const tones = {
    neutral: "bg-[var(--color-surface-muted)] text-[var(--color-ink-soft)]",
    accent: "bg-[color-mix(in_srgb,var(--color-accent)_12%,white)] text-[var(--color-accent)]",
    warm: "bg-[color-mix(in_srgb,var(--color-warm)_18%,white)] text-[#7a6532]",
    muted: "border border-[var(--color-line)] text-[var(--color-ink-soft)]",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...p}
    />
  );
}

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...p }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-9 w-full rounded-[10px] border border-[var(--color-line)] bg-[var(--color-surface)] px-3 text-sm outline-none placeholder:text-[var(--color-ink-soft)] focus:border-[var(--color-accent)]",
      className,
    )}
    {...p}
  />
));
Input.displayName = "Input";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...p }, ref) => (
  <select
    ref={ref}
    className={cn(
      "h-9 w-full rounded-[10px] border border-[var(--color-line)] bg-[var(--color-surface)] px-2.5 text-sm outline-none focus:border-[var(--color-accent)]",
      className,
    )}
    {...p}
  >
    {children}
  </select>
));
Select.displayName = "Select";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-[var(--color-surface-muted)]", className)}
    />
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block size-4 animate-spin rounded-full border-2 border-current border-t-transparent",
        className,
      )}
      role="status"
      aria-label="Loading"
    />
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-[14px] border border-dashed border-[var(--color-line)] bg-[var(--color-surface)] px-6 py-14 text-center">
      {icon && <div className="text-[var(--color-ink-soft)]">{icon}</div>}
      <p className="font-medium">{title}</p>
      {hint && <p className="max-w-sm text-sm text-[var(--color-ink-soft)]">{hint}</p>}
      {action}
    </div>
  );
}

/** Accessible slide-over used for property details and the mobile nav. */
export function Sheet({
  open,
  onClose,
  side = "right",
  labelledBy,
  children,
}: {
  open: boolean;
  onClose: () => void;
  side?: "right" | "left" | "bottom";
  labelledBy?: string;
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  const pos =
    side === "right"
      ? "right-0 top-0 h-full w-full max-w-md border-l"
      : side === "left"
        ? "left-0 top-0 h-full w-[86%] max-w-xs border-r"
        : "inset-x-0 bottom-0 max-h-[85vh] rounded-t-[18px] border-t";
  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-[rgba(23,33,29,0.28)]"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={cn(
          "absolute overflow-y-auto border-[var(--color-line)] bg-[var(--color-surface)] shadow-[var(--shadow-pop)]",
          pos,
        )}
      >
        {children}
      </div>
    </div>
  );
}
