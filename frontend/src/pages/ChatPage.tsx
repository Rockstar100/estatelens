import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useChat, useCompare } from "@/lib/store";
import { getSources, streamChat, toWireMessages } from "@/lib/api";
import type { ChatMessage, Property, SourcesResponse } from "@/types";
import { Composer } from "@/components/chat/Composer";
import { MessageBubble } from "@/components/chat/Message";
import { SourceDrawer, useSourceDrawer } from "@/components/chat/Citations";
import { PropertyDetails } from "@/components/PropertyDetails";

const FALLBACK_STARTERS = [
  "DarGlobal projects with waterfront living?",
  "Wasalt apartments for sale in Riyadh",
  "Cheapest Wasalt sale listing?",
  "Compare two DarGlobal developments",
];

/** Only send compare-tray ids when the user is clearly talking about them. */
function wantsCompareSelection(text: string): boolean {
  return /\b(compare|versus|vs\.?|difference between|these|those|selected|in (?:my )?compare|from (?:my )?compare)\b/i.test(
    text,
  );
}

/** Mirror backend should_carry_filters — don't sticky-lock on new factual turns. */
function shouldCarryFilters(text: string): boolean {
  const low = text.toLowerCase();
  if (/\b(start over|reset|clear filters?|show (?:me )?all|never ?mind)\b/.test(low)) return false;
  if (/\b(compare|versus|vs\.?)\b/.test(low)) return false;
  if (
    /\b(what about|how about|only|just|those|these|them|same|still|narrow|filter|also show|instead)\b/.test(
      low,
    ) &&
    !/\b(trump\s+tower|neptune|missoni|astera|ayla|ora|sidr|elenia)\b/.test(low)
  ) {
    return true;
  }
  if (
    /\b(what|when|where|who|how|tell me|describe)\b/.test(low) &&
    /\b(handover|price|cost|located|location|designer|interiors?|developer|completion|amenities|tower|project|development)\b/.test(
      low,
    )
  ) {
    return false;
  }
  if (/\b(trump\s+tower|neptune|missoni|astera|ayla|ora|sidr|elenia)\b/.test(low)) return false;
  return true;
}

export function ChatPage() {
  const {
    conversations,
    activeId,
    newConversation,
    appendMessage,
    updateLastAssistant,
    renameFromFirstMessage,
    takePendingPrompt,
    popLastTurn,
  } = useChat();
  const compare = useCompare();
  const drawer = useSourceDrawer();
  const [openProperty, setOpenProperty] = useState<Property | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<null | (() => void)>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [sources, setSources] = useState<SourcesResponse | null>(null);

  const conv = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? null,
    [conversations, activeId],
  );

  useEffect(() => {
    getSources().then(setSources).catch(() => undefined);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [conv?.messages]);

  const starters = useMemo(() => {
    if (!sources) return FALLBACK_STARTERS;
    const cities = sources.sources.flatMap((s) => s.cities).filter(Boolean);
    const out: string[] = [];
    if (sources.sources.some((s) => s.source === "darglobal"))
      out.push("DarGlobal projects with waterfront or golf-course living?");
    if (cities.includes("Riyadh")) out.push("Wasalt apartments for sale in Riyadh");
    else if (cities[0]) out.push(`Wasalt listings in ${cities[0]}`);
    out.push("Cheapest Wasalt sale listing?");
    out.push("Compare the first two properties you show me");
    return out.slice(0, 4);
  }, [sources]);

  const send = useCallback(
    async (text: string) => {
      const clean = text.trim();
      if (!clean || streaming) return;

      let id = activeId;
      if (!id || !conv) id = newConversation();

      // read the live store (the closure's `conversations` can be a render behind)
      const priorMsgs = (
        useChat.getState().conversations.find((c) => c.id === id)?.messages ?? []
      ).concat({ role: "user", content: clean } as ChatMessage);

      const userMsg: ChatMessage = { role: "user", content: clean };
      appendMessage(id, userMsg);
      appendMessage(id, { role: "assistant", content: "", pending: true });
      setInput("");
      setStreaming(true);

      const lastAssistant = [...priorMsgs]
        .reverse()
        .find((m) => m.role === "assistant" && !m.error);
      const context = {
        selected_property_ids: wantsCompareSelection(clean) ? compare.ids.slice(0, 3) : [],
        last_result_ids: (lastAssistant?.cards ?? []).map((p) => p.id),
        // carry filters only on refine turns — not on new named-project questions
        filters: shouldCarryFilters(clean) ? (lastAssistant?.appliedFilters ?? {}) : {},
      };

      let acc = "";
      const abort = streamChat(
        toWireMessages(priorMsgs),
        context,
        (e) => {
          if (e.type === "evidence")
            updateLastAssistant(id!, {
              evidence: e.items,
              appliedFilters: e.applied_filters,
            });
          else if (e.type === "cards") updateLastAssistant(id!, { cards: e.properties });
          else if (e.type === "delta") {
            acc += e.text;
            updateLastAssistant(id!, { content: acc, pending: true });
          } else if (e.type === "done")
            updateLastAssistant(id!, {
              pending: false,
              citations: e.citations,
              model: e.model,
            });
          else if (e.type === "error")
            updateLastAssistant(id!, {
              pending: false,
              error: { category: e.category, message: e.message },
            });
        },
        () => {
          setStreaming(false);
          abortRef.current = null;
          const live = useChat
            .getState()
            .conversations.find((c) => c.id === id)
            ?.messages.slice()
            .reverse()
            .find((m) => m.role === "assistant");
          if (live?.pending && !live.content.trim() && !live.error) {
            updateLastAssistant(id!, {
              pending: false,
              error: {
                category: "provider_unavailable",
                message: "No answer was returned. Please retry.",
              },
            });
          } else {
            updateLastAssistant(id!, { pending: false });
          }
          renameFromFirstMessage(id!);
        },
      );
      abortRef.current = abort;
    },
    [
      activeId,
      conv,
      conversations,
      streaming,
      compare.ids,
      appendMessage,
      newConversation,
      renameFromFirstMessage,
      updateLastAssistant,
      popLastTurn,
    ],
  );

  // A prompt queued from Explore / Compare / Details: send it once on arrival.
  useEffect(() => {
    const queued = takePendingPrompt();
    if (queued) send(queued);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => {
    // Clear pending before abort so onDone does not treat Stop as a failed answer.
    if (activeId) updateLastAssistant(activeId, { pending: false });
    abortRef.current?.();
    abortRef.current = null;
    setStreaming(false);
  };

  const retryLast = () => {
    if (!conv || streaming) return;
    const text = popLastTurn(conv.id);
    if (text) send(text);
  };

  const askAbout = (p: Property) => {
    setOpenProperty(null);
    send(
      `Tell me more about "${p.title}" (${p.source}). What does the collected source say about its price, location, and amenities?`,
    );
  };

  const messages = conv?.messages ?? [];
  const empty = messages.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
          {empty ? (
            <div className="pt-6 sm:pt-16">
              <h1 className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">
                Ask about DarGlobal &amp; Wasalt properties
              </h1>
              <p className="mt-2 text-[var(--color-ink-soft)]">
                Answers come only from collected public pages, with citations.
              </p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {starters.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-[12px] border border-[var(--color-line)] bg-[var(--color-surface)] px-3.5 py-3 text-left text-sm text-[var(--color-ink-soft)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-ink)]"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((m, i) => (
                <MessageBubble
                  key={i}
                  msg={m}
                  onOpenEvidence={drawer.open}
                  onOpenProperty={setOpenProperty}
                  onAskProperty={askAbout}
                  onRetry={
                    m.role === "assistant" && i === messages.length - 1 && !streaming
                      ? retryLast
                      : undefined
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-[var(--color-line)] bg-[var(--color-bg)]">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          <Composer
            value={input}
            onChange={setInput}
            onSend={() => send(input)}
            onStop={stop}
            streaming={streaming}
          />
        </div>
      </div>

      <SourceDrawer item={drawer.item} onClose={drawer.close} />
      <PropertyDetails
        propertyId={openProperty?.id ?? null}
        seed={openProperty}
        onClose={() => setOpenProperty(null)}
        onAsk={askAbout}
      />
    </div>
  );
}
