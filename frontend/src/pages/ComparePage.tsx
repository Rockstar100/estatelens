import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { X, ExternalLink, GitCompare } from "lucide-react";
import type { Property } from "@/types";
import { getProperty } from "@/lib/api";
import { useCompare, useChat } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { EmptyState, Badge, Skeleton } from "@/components/ui/primitives";
import { formatPrice, formatArea, titleCase } from "@/lib/utils";

const ROWS: { label: string; render: (p: Property) => React.ReactNode; note?: string }[] = [
  { label: "Source", render: (p) => <span className="capitalize">{p.source}</span> },
  { label: "Record type", render: (p) => <span className="capitalize">{p.record_type}</span> },
  {
    label: "Location",
    render: (p) => [p.district, p.city, p.country].filter(Boolean).join(", ") || "—",
  },
  {
    label: "Price",
    render: (p) => formatPrice(p.price_amount, p.price_currency, p.price_basis),
  },
  {
    label: "Price basis",
    render: (p) => (p.price_basis === "unspecified" ? "—" : p.price_basis.replace("_", " ")),
  },
  { label: "Bedrooms", render: (p) => (p.bedrooms === null ? "—" : p.bedrooms === 0 ? "Studio" : p.bedrooms) },
  { label: "Bathrooms", render: (p) => p.bathrooms ?? "—" },
  { label: "Area", render: (p) => formatArea(p.area_value, p.area_unit) ?? "—" },
  { label: "Property type", render: (p) => (p.property_type ? titleCase(p.property_type) : "—") },
  { label: "Developer", render: (p) => p.developer ?? "—" },
  { label: "Handover", render: (p) => p.completion_or_handover_text ?? "—" },
  {
    label: "Amenities",
    render: (p) =>
      p.amenities.length ? (
        <div className="flex flex-wrap gap-1">
          {p.amenities.slice(0, 10).map((a) => (
            <Badge key={a} tone="neutral">{a}</Badge>
          ))}
        </div>
      ) : (
        "—"
      ),
  },
  {
    label: "Source link",
    render: (p) => (
      <a
        href={p.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-[var(--color-accent)] hover:underline"
      >
        Open <ExternalLink className="size-3" />
      </a>
    ),
  },
];

export function ComparePage() {
  const { ids, cache, remove, clear } = useCompare();
  const { askInChat } = useChat();
  const navigate = useNavigate();
  const [props, setProps] = useState<Record<string, Property>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const missing = ids.filter((id) => !cache[id] && !props[id]);
    if (missing.length === 0) return;
    setLoading(true);
    Promise.all(missing.map((id) => getProperty(id).catch(() => null)))
      .then((list) => {
        const next: Record<string, Property> = {};
        list.forEach((p) => p && (next[p.id] = p));
        setProps((prev) => ({ ...prev, ...next }));
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);

  const resolved = ids.map((id) => cache[id] ?? props[id]).filter(Boolean) as Property[];

  const currencies = new Set(resolved.map((p) => p.price_currency).filter(Boolean));
  const bases = new Set(resolved.map((p) => p.price_basis).filter((b) => b !== "unspecified"));
  const incomparablePrice = currencies.size > 1 || bases.size > 1;

  const askToCompare = () => {
    if (!resolved.length) return;
    askInChat(
      `Compare these properties using only the collected sources: ${resolved
        .map((p) => `"${p.title}"`)
        .join(", ")}. Note anything that isn't directly comparable.`,
    );
    navigate("/");
  };

  if (ids.length === 0) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        <EmptyState
          icon={<GitCompare className="size-6" />}
          title="Nothing to compare yet"
          hint="Add up to three records from Explore or from a chat answer, then come back here."
          action={
            <Button variant="outline" size="sm" onClick={() => navigate("/explore")}>
              Go to Explore
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Compare</h1>
          <p className="text-sm text-[var(--color-ink-soft)]">
            {resolved.length} of 3 records. Fields come straight from stored records.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={askToCompare}>
            Ask AI to compare
          </Button>
          <Button variant="ghost" size="sm" onClick={clear}>
            <X /> Clear all
          </Button>
        </div>
      </div>

      {incomparablePrice && (
        <p className="mb-3 rounded-[10px] border border-[color-mix(in_srgb,var(--color-warm)_45%,white)] bg-[color-mix(in_srgb,var(--color-warm)_12%,white)] px-3 py-2 text-sm text-[#7a6532]">
          These records use different currencies or price bases (e.g. total vs. annual rent), so
          prices are <strong>not directly comparable</strong>.
        </p>
      )}

      {loading && resolved.length === 0 ? (
        <Skeleton className="h-96 w-full rounded-[14px]" />
      ) : (
        <div className="overflow-x-auto rounded-[14px] border border-[var(--color-line)] bg-[var(--color-surface)]">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-[var(--color-line)]">
                <th className="w-36 p-3 text-left text-xs font-medium uppercase tracking-wide text-[var(--color-ink-soft)]">
                  Field
                </th>
                {resolved.map((p) => (
                  <th key={p.id} className="p-3 text-left align-top">
                    <div className="flex items-start justify-between gap-2">
                      <span className="line-clamp-2 font-semibold">{p.title}</span>
                      <button
                        onClick={() => remove(p.id)}
                        aria-label={`Remove ${p.title}`}
                        className="shrink-0 rounded p-0.5 text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-muted)]"
                      >
                        <X className="size-3.5" />
                      </button>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.label} className="border-b border-[var(--color-line)] last:border-0">
                  <td className="p-3 align-top text-xs font-medium uppercase tracking-wide text-[var(--color-ink-soft)]">
                    {row.label}
                  </td>
                  {resolved.map((p) => (
                    <td key={p.id} className="nums p-3 align-top">
                      {row.render(p)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
