import { useState } from "react";
import { Building2, BedDouble, Ruler, MapPin, ExternalLink, GitCompare, MessageSquare } from "lucide-react";
import type { Property } from "@/types";
import { Card, Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { cn, formatPrice, formatArea, titleCase } from "@/lib/utils";
import { useCompare } from "@/lib/store";

interface Props {
  property: Property;
  onOpen: (p: Property) => void;
  onAsk?: (p: Property) => void;
  compact?: boolean;
}

/** Always load via our API so (a) old chat cards without image_url still work and
 *  (b) CDN / referrer quirks cannot blank the thumbnail. */
function propertyImageSrc(id: string): string {
  return `/api/properties/${encodeURIComponent(id)}/image`;
}

function PropertyThumb({
  property: p,
  className,
}: {
  property: Property;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const label = p.property_type ? titleCase(p.property_type) : titleCase(p.record_type);

  return (
    <div className={cn("relative overflow-hidden bg-[var(--color-surface-muted)]", className)}>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-[linear-gradient(145deg,#e8ebe6_0%,#f4f5f1_55%,#dde3dc_100%)]">
        <Building2 className="size-8 text-[color-mix(in_srgb,var(--color-accent)_30%,var(--color-line))]" />
        <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--color-ink-soft)]/75">
          {label}
        </span>
      </div>
      {!failed && (
        <img
          src={propertyImageSrc(p.id)}
          alt=""
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}

export function PropertyCard({ property: p, onOpen, onAsk, compact }: Props) {
  const compare = useCompare();
  const inCompare = compare.ids.includes(p.id);
  const location = [p.district, p.city, p.country].filter(Boolean).join(", ");

  if (compact) {
    return (
      <Card className="group flex overflow-hidden transition-shadow hover:shadow-[var(--shadow-soft)]">
        <button
          type="button"
          onClick={() => onOpen(p)}
          className="relative block h-auto w-[108px] shrink-0 self-stretch text-left sm:w-[124px]"
          aria-label={`View details for ${p.title}`}
        >
          <PropertyThumb property={p} className="absolute inset-0" />
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 p-3">
          <div className="flex flex-wrap gap-1">
            <Badge tone="accent" className="capitalize">
              {p.source}
            </Badge>
            <Badge tone="muted" className="capitalize">
              {p.record_type}
            </Badge>
          </div>
          <button type="button" onClick={() => onOpen(p)} className="text-left">
            <h3 className="line-clamp-2 text-[14px] font-semibold leading-snug tracking-tight">
              {p.title}
            </h3>
          </button>
          {location && (
            <p className="flex items-center gap-1 text-[11px] text-[var(--color-ink-soft)]">
              <MapPin className="size-3 shrink-0" />
              <span className="line-clamp-1">{location}</span>
            </p>
          )}
          <p className="nums text-[14px] font-semibold text-[var(--color-accent)]">
            {formatPrice(p.price_amount, p.price_currency, p.price_basis)}
          </p>
          <div className="flex flex-wrap gap-x-2.5 gap-y-0.5 text-[11px] text-[var(--color-ink-soft)]">
            {p.property_type && <span className="capitalize">{titleCase(p.property_type)}</span>}
            {p.bedrooms !== null && (
              <span className="flex items-center gap-0.5">
                <BedDouble className="size-3" /> {p.bedrooms === 0 ? "Studio" : `${p.bedrooms} bd`}
              </span>
            )}
            {formatArea(p.area_value, p.area_unit) && (
              <span className="flex items-center gap-0.5">
                <Ruler className="size-3" /> {formatArea(p.area_value, p.area_unit)}
              </span>
            )}
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="group flex flex-col overflow-hidden transition-shadow hover:shadow-[var(--shadow-soft)]">
      <button
        type="button"
        onClick={() => onOpen(p)}
        className="relative block aspect-[16/10] w-full text-left"
        aria-label={`View details for ${p.title}`}
      >
        <PropertyThumb property={p} className="absolute inset-0" />
        <div className="absolute left-2 top-2 flex gap-1.5">
          <Badge tone="accent" className="capitalize backdrop-blur">
            {p.source}
          </Badge>
          <Badge tone="muted" className="bg-[var(--color-surface)]/85 capitalize backdrop-blur">
            {p.record_type}
          </Badge>
        </div>
      </button>

      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <button type="button" onClick={() => onOpen(p)} className="text-left">
          <h3 className="line-clamp-2 text-[15px] font-semibold leading-snug tracking-tight">{p.title}</h3>
        </button>

        {location && (
          <p className="flex items-center gap-1 text-xs text-[var(--color-ink-soft)]">
            <MapPin className="size-3.5 shrink-0" />
            <span className="line-clamp-1">{location}</span>
          </p>
        )}

        <p className="nums text-[15px] font-semibold text-[var(--color-accent)]">
          {formatPrice(p.price_amount, p.price_currency, p.price_basis)}
        </p>

        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--color-ink-soft)]">
          {p.property_type && <span className="capitalize">{titleCase(p.property_type)}</span>}
          {p.bedrooms !== null && (
            <span className="flex items-center gap-1">
              <BedDouble className="size-3.5" /> {p.bedrooms === 0 ? "Studio" : `${p.bedrooms} bd`}
            </span>
          )}
          {formatArea(p.area_value, p.area_unit) && (
            <span className="flex items-center gap-1">
              <Ruler className="size-3.5" /> {formatArea(p.area_value, p.area_unit)}
            </span>
          )}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-1.5 pt-1">
          <Button size="sm" variant="outline" onClick={() => onOpen(p)}>
            View details
          </Button>
          {onAsk && (
            <Button size="sm" variant="ghost" onClick={() => onAsk(p)}>
              <MessageSquare /> Ask
            </Button>
          )}
          <Button
            size="sm"
            variant={inCompare ? "subtle" : "ghost"}
            onClick={() => (inCompare ? compare.remove(p.id) : compare.add(p))}
            disabled={!inCompare && compare.ids.length >= 3}
            title={compare.ids.length >= 3 && !inCompare ? "Comparison is full (3)" : undefined}
          >
            <GitCompare /> {inCompare ? "Added" : "Compare"}
          </Button>
          <a
            href={p.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "ml-auto inline-flex items-center gap-1 text-xs text-[var(--color-ink-soft)] hover:text-[var(--color-accent)]",
            )}
          >
            Source <ExternalLink className="size-3" />
          </a>
        </div>
      </div>
    </Card>
  );
}
