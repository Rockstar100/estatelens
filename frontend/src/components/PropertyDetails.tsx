import { useEffect, useState } from "react";
import { X, ExternalLink, GitCompare, MessageSquare, Building2 } from "lucide-react";
import type { Property } from "@/types";
import { Sheet, Badge, Skeleton } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { formatPrice, formatArea, relativeDate, titleCase } from "@/lib/utils";
import { getProperty } from "@/lib/api";
import { useCompare } from "@/lib/store";

interface Props {
  propertyId: string | null;
  seed?: Property | null;
  onClose: () => void;
  onAsk: (p: Property) => void;
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-[10px] bg-[var(--color-surface-muted)] px-3 py-2">
      <span className="text-[11px] uppercase tracking-wide text-[var(--color-ink-soft)]">{label}</span>
      <span className="nums text-sm font-medium">{value ?? <span className="text-[var(--color-ink-soft)]">Not listed in the collected source</span>}</span>
    </div>
  );
}

export function PropertyDetails({ propertyId, seed, onClose, onAsk }: Props) {
  const [prop, setProp] = useState<Property | null>(seed ?? null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const compare = useCompare();

  useEffect(() => {
    if (!propertyId) return;
    setErr(null);
    if (!seed || seed.id !== propertyId) {
      setLoading(true);
      setProp(null);
    }
    getProperty(propertyId)
      .then(setProp)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [propertyId, seed]);

  const inCompare = prop ? compare.ids.includes(prop.id) : false;

  return (
    <Sheet open={!!propertyId} onClose={onClose} labelledBy="pd-title">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--color-line)] bg-[var(--color-surface)] px-4 py-3">
        <span className="text-sm font-medium text-[var(--color-ink-soft)]">Property details</span>
        <button onClick={onClose} aria-label="Close details" className="rounded-md p-1 hover:bg-[var(--color-surface-muted)]">
          <X className="size-4" />
        </button>
      </div>

      <div className="space-y-5 p-4">
        {loading && (
          <div className="space-y-3">
            <Skeleton className="aspect-[16/10] w-full" />
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-20 w-full" />
          </div>
        )}
        {err && <p className="text-sm text-[#8a2b21]">Could not load this property: {err}</p>}

        {prop && (
          <>
            <div className="overflow-hidden rounded-[12px] border border-[var(--color-line)] bg-[var(--color-surface-muted)]">
              {prop.image_url ? (
                <>
                  <img
                    src={`/api/properties/${encodeURIComponent(prop.id)}/image`}
                    alt=""
                    className="aspect-[16/10] w-full object-cover"
                    onError={(e) => {
                      const el = e.currentTarget as HTMLImageElement;
                      el.style.display = "none";
                      const fallback = el.nextElementSibling as HTMLElement | null;
                      if (fallback) fallback.style.display = "flex";
                    }}
                  />
                  <div className="hidden aspect-[16/10] items-center justify-center" style={{ display: "none" }}>
                    <Building2 className="size-10 text-[var(--color-line)]" />
                  </div>
                </>
              ) : (
                <div className="flex aspect-[16/10] flex-col items-center justify-center gap-2 bg-[linear-gradient(145deg,#e8ebe6_0%,#f4f5f1_55%,#dde3dc_100%)]">
                  <Building2 className="size-10 text-[color-mix(in_srgb,var(--color-accent)_30%,var(--color-line))]" />
                  <span className="text-xs text-[var(--color-ink-soft)]">No photo in source</span>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                <Badge tone="accent" className="capitalize">{prop.source}</Badge>
                <Badge tone="muted" className="capitalize">{prop.record_type}</Badge>
                {prop.transaction_type !== "unspecified" && (
                  <Badge tone="warm" className="capitalize">For {prop.transaction_type}</Badge>
                )}
              </div>
              <h2 id="pd-title" className="text-lg font-semibold">{prop.title}</h2>
              <p className="text-sm text-[var(--color-ink-soft)]">
                {[prop.district, prop.city, prop.country].filter(Boolean).join(", ") || "Location not listed"}
              </p>
              <p className="nums text-lg font-semibold text-[var(--color-accent)]">
                {formatPrice(prop.price_amount, prop.price_currency, prop.price_basis)}
              </p>
              {prop.original_price_text && (
                <p className="text-xs text-[var(--color-ink-soft)]">As published: “{prop.original_price_text}”</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Fact label="Type" value={prop.property_type ? titleCase(prop.property_type) : null} />
              <Fact label="Bedrooms" value={prop.bedrooms === null ? null : prop.bedrooms === 0 ? "Studio" : prop.bedrooms} />
              <Fact label="Bathrooms" value={prop.bathrooms ?? null} />
              <Fact label="Area" value={formatArea(prop.area_value, prop.area_unit)} />
              <Fact label="Developer" value={prop.developer ?? null} />
              <Fact label="Handover" value={prop.completion_or_handover_text ?? null} />
            </div>

            {prop.description && (
              <div>
                <h3 className="mb-1 text-sm font-semibold">Description</h3>
                <p className="whitespace-pre-line text-sm text-[var(--color-ink-soft)]">{prop.description}</p>
              </div>
            )}

            <div>
              <h3 className="mb-1.5 text-sm font-semibold">Amenities</h3>
              {prop.amenities.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {prop.amenities.map((a) => (
                    <Badge key={a} tone="neutral">{a}</Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-[var(--color-ink-soft)]">Not listed in the collected source.</p>
              )}
            </div>

            <div className="rounded-[10px] border border-[var(--color-line)] px-3 py-2 text-xs text-[var(--color-ink-soft)]">
              From <span className="font-medium capitalize">{prop.source}</span>, {relativeDate(prop.scraped_at)} · not live inventory
            </div>

            <div className="flex flex-wrap gap-2">
              <Button onClick={() => onAsk(prop)}>
                <MessageSquare /> Ask about this property
              </Button>
              <Button
                variant="outline"
                onClick={() => (inCompare ? compare.remove(prop.id) : compare.add(prop))}
                disabled={!inCompare && compare.ids.length >= 3}
              >
                <GitCompare /> {inCompare ? "In comparison" : "Add to comparison"}
              </Button>
              <a href={prop.source_url} target="_blank" rel="noopener noreferrer">
                <Button variant="ghost">
                  View source <ExternalLink />
                </Button>
              </a>
            </div>
          </>
        )}
      </div>
    </Sheet>
  );
}
