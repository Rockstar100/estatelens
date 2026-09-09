import { useState } from "react";
import { ExternalLink, X, FileText } from "lucide-react";
import type { EvidenceItem } from "@/types";
import { Sheet, Badge } from "@/components/ui/primitives";
import { relativeDate } from "@/lib/utils";

/** Renders assistant markdown text with [E#] turned into clickable chips. */
export function CitedText({
  text,
  evidence,
  onOpen,
}: {
  text: string;
  evidence: EvidenceItem[];
  onOpen: (e: EvidenceItem) => void;
}) {
  const byOrdinal = new Map(evidence.map((e) => [e.ordinal, e]));
  const parts = text.split(/(\[E\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[E(\d+)\]$/);
        if (!m) return <span key={i}>{part}</span>;
        const ev = byOrdinal.get(Number(m[1]));
        if (!ev)
          return (
            <sup key={i} className="text-[var(--color-ink-soft)]">
              [{m[1]}]
            </sup>
          );
        return (
          <button
            key={i}
            onClick={() => onOpen(ev)}
            className="mx-0.5 inline-flex items-center rounded-md bg-[color-mix(in_srgb,var(--color-accent)_12%,white)] px-1.5 align-baseline text-[11px] font-semibold text-[var(--color-accent)] hover:bg-[color-mix(in_srgb,var(--color-accent)_20%,white)]"
            title={ev.title ?? ev.site}
          >
            {ev.ordinal}
          </button>
        );
      })}
    </>
  );
}

export function EvidenceList({
  evidence,
  onOpen,
}: {
  evidence: EvidenceItem[];
  onOpen: (e: EvidenceItem) => void;
}) {
  if (!evidence.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {evidence.map((e) => (
        <button
          key={e.id}
          onClick={() => onOpen(e)}
          className="inline-flex max-w-[240px] items-center gap-1.5 rounded-full border border-[var(--color-line)] bg-[var(--color-surface)] px-2 py-1 text-xs hover:border-[var(--color-accent)]"
        >
          <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-[var(--color-surface-muted)] text-[10px] font-semibold">
            {e.ordinal}
          </span>
          <span className="truncate text-[var(--color-ink-soft)]">{e.title ?? e.site}</span>
        </button>
      ))}
    </div>
  );
}

export function SourceDrawer({
  item,
  onClose,
}: {
  item: EvidenceItem | null;
  onClose: () => void;
}) {
  return (
    <Sheet open={!!item} onClose={onClose} side="right" labelledBy="sd-title">
      {item && (
        <div className="p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-[var(--color-ink-soft)]" />
              <Badge tone="accent">{item.site}</Badge>
            </div>
            <button onClick={onClose} aria-label="Close source" className="rounded-md p-1 hover:bg-[var(--color-surface-muted)]">
              <X className="size-4" />
            </button>
          </div>
          <h3 id="sd-title" className="text-base font-semibold">
            {item.title ?? "Source passage"}
          </h3>
          {item.section_heading && (
            <p className="mt-0.5 text-sm text-[var(--color-ink-soft)]">{item.section_heading}</p>
          )}
          <p className="mt-3 whitespace-pre-line rounded-[10px] bg-[var(--color-surface-muted)] p-3 text-sm">
            {item.excerpt}
          </p>
          <p className="mt-3 text-xs text-[var(--color-ink-soft)]">
            Collected {relativeDate(item.collected_at)} · citation id <code className="text-[11px]">{item.id}</code>
          </p>
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--color-accent)] hover:underline"
          >
            Open original page <ExternalLink className="size-3.5" />
          </a>
        </div>
      )}
    </Sheet>
  );
}

export function useSourceDrawer() {
  const [item, setItem] = useState<EvidenceItem | null>(null);
  return { item, open: setItem, close: () => setItem(null) };
}
