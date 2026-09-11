import { useEffect, useState } from "react";
import { Database, FileText, Building2, AlertTriangle, Cpu, Search } from "lucide-react";
import type { SourcesResponse } from "@/types";
import { getSources } from "@/lib/api";
import { Card, Skeleton, Badge } from "@/components/ui/primitives";
import { relativeDate } from "@/lib/utils";

function Stat({ icon, value, label }: { icon: React.ReactNode; value: React.ReactNode; label: string }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <div className="flex size-9 items-center justify-center rounded-[10px] bg-[var(--color-surface-muted)] text-[var(--color-ink-soft)]">
        {icon}
      </div>
      <div>
        <p className="nums text-lg font-semibold">{value}</p>
        <p className="text-xs text-[var(--color-ink-soft)]">{label}</p>
      </div>
    </Card>
  );
}

export function SourcesPage() {
  const [data, setData] = useState<SourcesResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getSources().then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err)
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <p className="text-sm text-[#8a2b21]">Could not load coverage: {err}</p>
      </div>
    );

  if (!data)
    return (
      <div className="mx-auto max-w-4xl space-y-4 px-4 py-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-3 sm:grid-cols-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
        <Skeleton className="h-64" />
      </div>
    );

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Sources &amp; About</h1>
        <p className="text-sm text-[var(--color-ink-soft)]">
          What was collected, and how answers are grounded in it.
        </p>
      </div>

      <Card className="p-4">
        <h2 className="mb-3 font-semibold">Assignment checklist</h2>
        <ul className="space-y-2.5 text-sm">
          {[
            {
              t: "Scrape DarGlobal & Wasalt",
              d: `${data.total_documents} public pages collected into MongoDB (CLI crawler only — never from chat).`,
            },
            {
              t: "AI chatbot on collected data",
              d: "Answers only from retrieved passages + property records, with [E#] citations.",
            },
            {
              t: "Free LLM provider",
              d: `${data.model}${data.fallback_model && data.fallback_model !== "(none configured)" ? ` · then ${data.fallback_model}` : ""}.`,
            },
            {
              t: "Containerised with Docker",
              d: "Multi-stage image: Vite SPA + FastAPI on one origin.",
            },
            {
              t: "Deployed with a working URL",
              d: "Health: /api/health",
              href: "https://estatelens.onrender.com/",
              hrefLabel: "estatelens.onrender.com",
            },
          ].map((row) => (
            <li key={row.t} className="flex gap-3">
              <span className="mt-1.5 size-2 shrink-0 rounded-full bg-[var(--color-accent)]" />
              <div>
                <p className="font-medium text-[var(--color-ink)]">{row.t}</p>
                <p className="text-[var(--color-ink-soft)]">
                  {"href" in row && row.href ? (
                    <>
                      <a
                        href={row.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[var(--color-accent)] hover:underline"
                      >
                        {row.hrefLabel}
                      </a>
                      {" — "}
                      {row.d}
                    </>
                  ) : (
                    row.d
                  )}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat icon={<Building2 className="size-4" />} value={data.total_properties} label="Property records" />
        <Stat icon={<FileText className="size-4" />} value={data.total_documents} label="Source pages" />
        <Stat icon={<Database className="size-4" />} value={data.total_passages} label="Retrievable passages" />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {data.sources.map((s) => (
          <Card key={s.source} className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold capitalize">{s.source}</h2>
              <a
                href={`https://${s.site}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-[var(--color-accent)] hover:underline"
              >
                {s.site}
              </a>
            </div>
            <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
              <dt className="text-[var(--color-ink-soft)]">Pages</dt>
              <dd className="nums text-right">{s.document_count}</dd>
              <dt className="text-[var(--color-ink-soft)]">Properties</dt>
              <dd className="nums text-right">{s.property_count}</dd>
              <dt className="text-[var(--color-ink-soft)]">Listings / developments</dt>
              <dd className="nums text-right">
                {s.listing_count} / {s.development_count}
              </dd>
              <dt className="text-[var(--color-ink-soft)]">Latest collection</dt>
              <dd className="text-right">{relativeDate(s.latest_collection)}</dd>
              <dt className="text-[var(--color-ink-soft)]">Extraction failures</dt>
              <dd className="nums text-right">{s.extraction_failures}</dd>
            </dl>
            {s.cities.length > 0 && (
              <div className="mt-3">
                <p className="mb-1 text-xs text-[var(--color-ink-soft)]">Locations covered</p>
                <div className="flex flex-wrap gap-1">
                  {s.cities.map((c) => (
                    <Badge key={c} tone="neutral">{c}</Badge>
                  ))}
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>

      {data.coverage_gaps.length > 0 && (
        <Card className="p-4">
          <h2 className="mb-2 flex items-center gap-2 font-semibold">
            <AlertTriangle className="size-4 text-[var(--color-warm)]" /> Coverage gaps
          </h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--color-ink-soft)]">
            {data.coverage_gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-1.5 flex items-center gap-2 font-semibold">
            <Search className="size-4" /> Retrieval method
          </h2>
          <p className="text-sm text-[var(--color-ink-soft)]">{data.retrieval_method}</p>
        </Card>
        <Card className="p-4">
          <h2 className="mb-1.5 flex items-center gap-2 font-semibold">
            <Cpu className="size-4" /> Model
          </h2>
          <p className="text-sm text-[var(--color-ink-soft)]">
            Primary: <code className="text-[13px]">{data.model}</code>
            <br />
            Next in chain: <code className="text-[13px]">{data.fallback_model}</code>
            <br />
            Tested: {data.model_tested_on}
          </p>
        </Card>
      </div>

      <Card className="p-4">
        <h2 className="mb-1.5 font-semibold">Architecture</h2>
        <p className="text-sm text-[var(--color-ink-soft)]">
          React + Vite SPA served by a FastAPI backend from a single origin. Public pages from
          DarGlobal and Wasalt are collected by a CLI crawler (browser-rendered where a JS
          challenge requires it), normalized, and stored in MongoDB as{" "}
          <code className="text-[13px]">properties</code>,{" "}
          <code className="text-[13px]">documents</code> and{" "}
          <code className="text-[13px]">passages</code>. Chat answers are produced by a free LLM
          (Groq, Gemini, or OpenRouter — whichever keys are configured) constrained to the retrieved
          passages, with citations resolved from stored records. The public instance runs on Render
          at{" "}
          <a
            href="https://estatelens.onrender.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--color-accent)] hover:underline"
          >
            estatelens.onrender.com
          </a>
          . This is an independent demo and is not affiliated with DarGlobal or Wasalt.
        </p>
      </Card>
    </div>
  );
}
