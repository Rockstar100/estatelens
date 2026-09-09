import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Search, SlidersHorizontal, X } from "lucide-react";
import type { Facets, Property } from "@/types";
import { listProperties, type PropertyQuery } from "@/lib/api";
import { PropertyCard } from "@/components/PropertyCard";
import { PropertyDetails } from "@/components/PropertyDetails";
import { Button } from "@/components/ui/button";
import { Input, Select, Skeleton, EmptyState } from "@/components/ui/primitives";
import { titleCase } from "@/lib/utils";
import { useChat } from "@/lib/store";

const PAGE_SIZE = 12;
type FilterKey =
  | "text" | "source" | "city" | "record_type" | "transaction_type"
  | "property_type" | "bedrooms" | "budget_max" | "currency" | "sort";

export function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { askInChat } = useChat();

  const [items, setItems] = useState<Property[]>([]);
  const [facets, setFacets] = useState<Facets>({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Property | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const debounce = useRef<number>(0);

  const get = (k: FilterKey) => params.get(k) ?? "";
  const setFilter = (k: FilterKey, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
    setPage(1);
  };
  const clearFilters = () => {
    setParams(new URLSearchParams(), { replace: true });
    setPage(1);
  };

  const buildQuery = useCallback(
    (p: number): PropertyQuery => ({
      text: get("text") || undefined,
      source: get("source") || undefined,
      city: get("city") || undefined,
      record_type: get("record_type") || undefined,
      transaction_type: get("transaction_type") || undefined,
      property_type: get("property_type") || undefined,
      bedrooms: get("bedrooms") ? Number(get("bedrooms")) : undefined,
      budget_max: get("budget_max") ? Number(get("budget_max")) : undefined,
      currency: get("currency") || undefined,
      sort: get("sort") || undefined,
      page: p,
      page_size: PAGE_SIZE,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params],
  );

  useEffect(() => {
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      setLoading(true);
      setErr(null);
      listProperties(buildQuery(1))
        .then((r) => {
          setItems(r.items);
          setFacets(r.facets);
          setTotal(r.total);
          setPage(1);
        })
        .catch((e) => setErr(e.message))
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(debounce.current);
  }, [buildQuery]);

  const loadMore = () => {
    const next = page + 1;
    listProperties(buildQuery(next)).then((r) => {
      setItems((prev) => [...prev, ...r.items]);
      setPage(next);
    });
  };

  const askAbout = (p: Property) => {
    askInChat(
      `Tell me about "${p.title}" from ${p.source}. What is in the collected source about its price, location and amenities?`,
    );
    navigate("/");
  };

  const facetOptions = (key: keyof Facets) =>
    (facets[key] ?? []).map((f) => f.value).filter(Boolean);

  const activeCount = ["source", "city", "record_type", "transaction_type", "property_type", "bedrooms", "budget_max", "currency"].filter((k) => params.get(k)).length;

  const FilterFields = (
    <>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">Source</label>
        <Select value={get("source")} onChange={(e) => setFilter("source", e.target.value)}>
          <option value="">All sources</option>
          {facetOptions("sources").map((v) => (
            <option key={v} value={v}>{titleCase(v)}</option>
          ))}
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">City</label>
        <Select value={get("city")} onChange={(e) => setFilter("city", e.target.value)}>
          <option value="">Any city</option>
          {facetOptions("cities").map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">Record type</label>
        <Select value={get("record_type")} onChange={(e) => setFilter("record_type", e.target.value)}>
          <option value="">Listings & developments</option>
          {facetOptions("record_types").map((v) => (
            <option key={v} value={v}>{titleCase(v)}</option>
          ))}
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">Sale / rent</label>
        <Select value={get("transaction_type")} onChange={(e) => setFilter("transaction_type", e.target.value)}>
          <option value="">Any</option>
          <option value="sale">For sale</option>
          <option value="rent">For rent</option>
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">Property type</label>
        <Select value={get("property_type")} onChange={(e) => setFilter("property_type", e.target.value)}>
          <option value="">Any type</option>
          {facetOptions("property_types").map((v) => (
            <option key={v} value={v}>{titleCase(v)}</option>
          ))}
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">Bedrooms</label>
        <Select value={get("bedrooms")} onChange={(e) => setFilter("bedrooms", e.target.value)}>
          <option value="">Any</option>
          {facetOptions("bedrooms")
            .map(Number)
            .sort((a, b) => a - b)
            .map((n) => (
              <option key={n} value={n}>{n === 0 ? "Studio" : n}</option>
            ))}
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">
          Max budget
        </label>
        <div className="flex gap-1.5">
          <Input
            type="number"
            inputMode="numeric"
            placeholder="e.g. 2000000"
            value={get("budget_max")}
            onChange={(e) => setFilter("budget_max", e.target.value)}
          />
          <Select
            className="w-24"
            value={get("currency")}
            onChange={(e) => setFilter("currency", e.target.value)}
          >
            <option value="">Cur.</option>
            {facetOptions("currencies").map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </Select>
        </div>
        {get("budget_max") && !get("currency") && (
          <p className="mt-1 text-[11px] text-[var(--color-warm)]">
            Pick a currency — budgets across currencies aren't comparable.
          </p>
        )}
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-ink-soft)]">Sort</label>
        <Select value={get("sort")} onChange={(e) => setFilter("sort", e.target.value)}>
          <option value="relevance">Relevance</option>
          <option value="price_asc">Price: low to high</option>
          <option value="price_desc">Price: high to low</option>
          <option value="newest">Recently collected</option>
        </Select>
      </div>
    </>
  );

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Explore</h1>
          <p className="text-sm text-[var(--color-ink-soft)]">
            {loading ? "Loading…" : `${total} record${total === 1 ? "" : "s"} match your filters`}
          </p>
        </div>
        <Button
          variant="outline"
          className="sm:hidden"
          onClick={() => setShowFilters((s) => !s)}
        >
          <SlidersHorizontal /> Filters {activeCount > 0 && `(${activeCount})`}
        </Button>
      </div>

      <div className="relative mb-4">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--color-ink-soft)]" />
        <Input
          className="pl-9"
          placeholder="Search titles, descriptions, amenities…"
          defaultValue={get("text")}
          onChange={(e) => setFilter("text", e.target.value)}
        />
      </div>

      <div className="grid gap-5 sm:grid-cols-[220px_1fr]">
        <aside className={`${showFilters ? "block" : "hidden"} space-y-3 sm:block`}>
          {FilterFields}
          {activeCount > 0 && (
            <Button variant="ghost" size="sm" className="w-full" onClick={clearFilters}>
              <X /> Clear filters
            </Button>
          )}
        </aside>

        <div>
          {err && (
            <p className="rounded-[10px] border border-[#f0d9d5] bg-[#fdf3f2] p-3 text-sm text-[#8a2b21]">
              Could not load properties: {err}
            </p>
          )}
          {loading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-72 w-full rounded-[14px]" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              title="No records match"
              hint="Try removing a filter — for example a bedroom count or budget that no collected record meets."
              action={
                activeCount > 0 ? (
                  <Button variant="outline" size="sm" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((p) => (
                  <PropertyCard key={p.id} property={p} onOpen={setOpen} onAsk={askAbout} />
                ))}
              </div>
              {page * PAGE_SIZE < total && (
                <div className="mt-6 flex justify-center">
                  <Button variant="outline" onClick={loadMore}>
                    Load more ({total - page * PAGE_SIZE} left)
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <PropertyDetails
        propertyId={open?.id ?? null}
        seed={open}
        onClose={() => setOpen(null)}
        onAsk={askAbout}
      />
    </div>
  );
}
