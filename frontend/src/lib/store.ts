import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Conversation, ChatMessage, Property } from "@/types";
import { shortId } from "./utils";

interface ChatState {
  conversations: Conversation[];
  activeId: string | null;
  /** A prompt queued by Explore/Compare/Details; ChatPage sends it on mount. */
  pendingPrompt: string | null;
  newConversation: () => string;
  setActive: (id: string) => void;
  deleteConversation: (id: string) => void;
  clearAll: () => void;
  appendMessage: (id: string, msg: ChatMessage) => void;
  updateLastAssistant: (id: string, patch: Partial<ChatMessage>) => void;
  /** Drop the trailing user + assistant pair (used by Retry). */
  popLastTurn: (id: string) => string | null;
  renameFromFirstMessage: (id: string) => void;
  /** Queue a prompt and start a fresh conversation for it. */
  askInChat: (prompt: string) => void;
  takePendingPrompt: () => string | null;
}

export const useChat = create<ChatState>()(
  persist(
    (set, get) => ({
      conversations: [],
      activeId: null,
      pendingPrompt: null,
      newConversation: () => {
        const id = shortId();
        const conv: Conversation = {
          id,
          title: "New conversation",
          createdAt: Date.now(),
          updatedAt: Date.now(),
          messages: [],
        };
        set((s) => ({ conversations: [conv, ...s.conversations], activeId: id }));
        return id;
      },
      setActive: (id) => set({ activeId: id }),
      deleteConversation: (id) =>
        set((s) => {
          const rest = s.conversations.filter((c) => c.id !== id);
          return { conversations: rest, activeId: s.activeId === id ? (rest[0]?.id ?? null) : s.activeId };
        }),
      clearAll: () => set({ conversations: [], activeId: null }),
      appendMessage: (id, msg) =>
        set((s) => ({
          conversations: s.conversations.map((c) =>
            c.id === id ? { ...c, messages: [...c.messages, msg], updatedAt: Date.now() } : c,
          ),
        })),
      updateLastAssistant: (id, patch) =>
        set((s) => ({
          conversations: s.conversations.map((c) => {
            if (c.id !== id) return c;
            const msgs = [...c.messages];
            for (let i = msgs.length - 1; i >= 0; i--) {
              if (msgs[i].role === "assistant") {
                msgs[i] = { ...msgs[i], ...patch };
                break;
              }
            }
            return { ...c, messages: msgs, updatedAt: Date.now() };
          }),
        })),
      popLastTurn: (id) => {
        const conv = get().conversations.find((c) => c.id === id);
        if (!conv) return null;
        const msgs = [...conv.messages];
        if (msgs.length && msgs[msgs.length - 1]?.role === "assistant") msgs.pop();
        let userText: string | null = null;
        if (msgs.length && msgs[msgs.length - 1]?.role === "user") {
          userText = msgs[msgs.length - 1].content;
          msgs.pop();
        }
        set((s) => ({
          conversations: s.conversations.map((c) =>
            c.id === id ? { ...c, messages: msgs, updatedAt: Date.now() } : c,
          ),
        }));
        return userText;
      },
      renameFromFirstMessage: (id) =>
        set((s) => ({
          conversations: s.conversations.map((c) => {
            if (c.id !== id || c.title !== "New conversation") return c;
            const first = c.messages.find((m) => m.role === "user");
            if (!first) return c;
            return { ...c, title: first.content.slice(0, 48) + (first.content.length > 48 ? "…" : "") };
          }),
        })),
      askInChat: (prompt) => {
        const trimmed = prompt.trim().slice(0, 4000);
        if (!trimmed) return;
        const id = shortId();
        const conv: Conversation = {
          id,
          title: "New conversation",
          createdAt: Date.now(),
          updatedAt: Date.now(),
          messages: [],
        };
        set((s) => ({
          conversations: [conv, ...s.conversations],
          activeId: id,
          pendingPrompt: trimmed,
        }));
      },
      takePendingPrompt: () => {
        const p = get().pendingPrompt;
        if (p) set({ pendingPrompt: null });
        return p;
      },
    }),
    {
      name: "estatelens.conversations",
      partialize: (s) => ({ conversations: s.conversations, activeId: s.activeId }),
      // A crashed/tab-closed stream can leave pending:true forever in localStorage.
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<ChatState>;
        const conversations = (p.conversations ?? current.conversations).map((c) => ({
          ...c,
          messages: c.messages.map((m) =>
            m.role === "assistant" && m.pending ? { ...m, pending: false } : m,
          ),
        }));
        return {
          ...current,
          ...p,
          conversations,
          activeId: p.activeId ?? current.activeId,
          pendingPrompt: null,
        };
      },
    },
  ),
);

interface CompareState {
  ids: string[];
  cache: Record<string, Property>;
  add: (p: Property) => void;
  remove: (id: string) => void;
  clear: () => void;
  has: (id: string) => boolean;
}

export const useCompare = create<CompareState>()(
  persist(
    (set, get) => ({
      ids: [],
      cache: {},
      add: (p) =>
        set((s) =>
          s.ids.includes(p.id) || s.ids.length >= 3
            ? s
            : { ids: [...s.ids, p.id], cache: { ...s.cache, [p.id]: p } },
        ),
      remove: (id) =>
        set((s) => ({ ids: s.ids.filter((x) => x !== id) })),
      clear: () => set({ ids: [] }),
      has: (id) => get().ids.includes(id),
    }),
    { name: "estatelens.compare" },
  ),
);
