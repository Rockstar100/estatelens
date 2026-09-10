import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { Copy, RefreshCw, Check, AlertTriangle, Sparkles } from "lucide-react";
import type { ChatMessage, EvidenceItem, Property } from "@/types";
import { CitedText, EvidenceList } from "./Citations";
import { PropertyCard } from "@/components/PropertyCard";
import { Spinner } from "@/components/ui/primitives";

const ERR_COPY: Record<string, string> = {
  quota_exhausted:
    "The free model quota is used up for now. Browsing still works; try the chat again later.",
  provider_unavailable: "The model is unavailable right now. Browsing still works — please retry shortly.",
  timeout: "The model took too long to respond. Please try again.",
  rate_limited: "The AI provider is busy right now. Wait a few seconds and retry.",
  internal: "Something went wrong handling that request.",
  bad_request: "That request could not be processed.",
};

export function MessageBubble({
  msg,
  onOpenEvidence,
  onOpenProperty,
  onAskProperty,
  onRetry,
}: {
  msg: ChatMessage;
  onOpenEvidence: (e: EvidenceItem) => void;
  onOpenProperty: (p: Property) => void;
  onAskProperty: (p: Property) => void;
  onRetry?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-[14px] rounded-br-sm bg-[var(--color-accent)] px-3.5 py-2.5 text-sm text-white">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--color-accent)_14%,white)] text-[var(--color-accent)]">
        <Sparkles className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        {msg.evidence && msg.evidence.length > 0 && (
          <details className="group mb-2">
            <summary className="cursor-pointer list-none text-xs font-medium text-[var(--color-ink-soft)] hover:text-[var(--color-ink)]">
              {msg.evidence.length} source{msg.evidence.length > 1 ? "s" : ""}
              <span className="ml-1 opacity-60 group-open:hidden">▸</span>
              <span className="ml-1 hidden opacity-60 group-open:inline">▾</span>
            </summary>
            <EvidenceList evidence={msg.evidence} onOpen={onOpenEvidence} />
          </details>
        )}

        {msg.error ? (
          <div className="flex items-start gap-2 rounded-[12px] border border-[#f0d9d5] bg-[#fdf3f2] px-3 py-2.5 text-sm text-[#8a2b21]">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <div>
              <p className="font-medium">AI answer unavailable</p>
              <p className="mt-0.5 text-[13px]">{ERR_COPY[msg.error.category] ?? msg.error.message}</p>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="mt-1.5 inline-flex items-center gap-1 text-[13px] font-medium underline"
                >
                  <RefreshCw className="size-3.5" /> Retry
                </button>
              )}
            </div>
          </div>
        ) : msg.content ? (
          <div className="markdown text-[15px] leading-relaxed">
            {renderWithCitations(msg.content, msg.evidence ?? [], onOpenEvidence)}
            {msg.pending && <span className="caret" />}
          </div>
        ) : null}

        {/* Show the matched property while the model writes — pipeline already caps cards. */}
        {msg.cards && msg.cards.length > 0 && (
          <div className="mt-3 grid gap-2.5">
            {msg.cards.map((p) => (
              <PropertyCard
                key={p.id}
                property={p}
                onOpen={onOpenProperty}
                onAsk={onAskProperty}
                compact
              />
            ))}
          </div>
        )}

        {!msg.pending && !msg.error && msg.content && (
          <div className="mt-2 flex items-center gap-3 text-xs text-[var(--color-ink-soft)]">
            <button
              className="inline-flex items-center gap-1 hover:text-[var(--color-ink)]"
              onClick={() => {
                navigator.clipboard.writeText(msg.content);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
            {onRetry && (
              <button className="inline-flex items-center gap-1 hover:text-[var(--color-ink)]" onClick={onRetry}>
                <RefreshCw className="size-3.5" /> Retry
              </button>
            )}
            {msg.model && <span className="ml-auto opacity-70">{msg.model}</span>}
          </div>
        )}

        {msg.pending && !msg.content && !msg.error && (
          <p className="mt-2 flex items-center gap-2 text-sm text-[var(--color-ink-soft)]">
            <Spinner />
            {msg.evidence?.length || msg.cards?.length ? "Writing answer…" : "Searching…"}
          </p>
        )}
      </div>
    </div>
  );
}

function renderWithCitations(
  text: string,
  evidence: EvidenceItem[],
  onOpen: (e: EvidenceItem) => void,
) {
  // Render markdown, then post-process text nodes for [E#] chips.
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={{
        p: ({ children }) => <p>{childrenWithCitations(children, evidence, onOpen)}</p>,
        li: ({ children }) => <li>{childrenWithCitations(children, evidence, onOpen)}</li>,
        a: ({ href, children }) => {
          const safe = href && /^https?:\/\//i.test(href) ? href : undefined;
          return safe ? (
            <a href={safe} target="_blank" rel="noopener noreferrer nofollow">
              {children}
            </a>
          ) : (
            <span>{children}</span>
          );
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function childrenWithCitations(
  children: React.ReactNode,
  evidence: EvidenceItem[],
  onOpen: (e: EvidenceItem) => void,
): React.ReactNode {
  if (typeof children === "string") {
    return <CitedText text={children} evidence={evidence} onOpen={onOpen} />;
  }
  if (Array.isArray(children)) {
    return children.map((c, i) =>
      typeof c === "string" ? (
        <CitedText key={i} text={c} evidence={evidence} onOpen={onOpen} />
      ) : (
        c
      ),
    );
  }
  return children;
}
