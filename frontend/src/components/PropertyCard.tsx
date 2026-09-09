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

export function PropertyCard({ property: p, onOpen, onAsk, compact }: Props) {
  const compare = useCompare();
  const inCompare = compare.ids.includes(p.id);
  const location = [p.district, p.city, p.country].filter(Boolean).join(", ");

  return (
    <Card className="group flex flex-col overflow-hidden transition-shadow hover:shadow-[var(--shadow-soft)]">
      <button
        onClick={() => onOpen(p)}
        className="relative block aspect-[16/10] w-full overflow-hidden bg-[var(--color-surface-muted)] text-left"
        aria-label={`View details for ${p.title}`}
      >
        {p.image_url ? (
          <img
            src={p.image_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
              (e.currentTarget.parentElement as HTMLElement).dataset.fallback = "1";
            }}
          />
        ) : null}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center [[data-fallback='1']_&]:flex">
          {!p.image_url && <Building2 className="size-8 text-[var(--color-line)]" />}
        </div>
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
        <button onClick={() => onOpen(p)} className="text-left">
          <h3 className="line-clamp-2 text-[15px] font-semibold leading-snug">{p.title}</h3>
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

        {!compact && (
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
        )}
      </div>
    </Card>
  );
}
