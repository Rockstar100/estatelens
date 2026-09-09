import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { SidebarContent } from "@/components/Sidebar";
import { Sheet } from "@/components/ui/primitives";
import { ChatPage } from "@/pages/ChatPage";
import { ExplorePage } from "@/pages/ExplorePage";
import { ComparePage } from "@/pages/ComparePage";
import { SourcesPage } from "@/pages/SourcesPage";
import { useChat } from "@/lib/store";

function Shell() {
  const [mobileNav, setMobileNav] = useState(false);
  const { conversations, activeId, newConversation, setActive } = useChat();

  // Make sure a conversation exists so the chat page has somewhere to write.
  useEffect(() => {
    if (!activeId || !conversations.find((c) => c.id === activeId)) {
      if (conversations.length) setActive(conversations[0].id);
      else newConversation();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-[var(--color-bg)]">
      <aside className="hidden w-[240px] shrink-0 border-r border-[var(--color-line)] bg-[var(--color-surface)] md:block">
        <SidebarContent />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-[var(--color-line)] bg-[var(--color-surface)] px-3 py-2 md:hidden">
          <button
            onClick={() => setMobileNav(true)}
            aria-label="Open navigation"
            className="rounded-md p-1.5 hover:bg-[var(--color-surface-muted)]"
          >
            <Menu className="size-5" />
          </button>
          <span className="font-semibold">EstateLens</span>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/explore" element={<ExplorePage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="*" element={<ChatPage />} />
          </Routes>
        </main>
      </div>

      <Sheet open={mobileNav} onClose={() => setMobileNav(false)} side="left" labelledBy="nav-title">
        <div className="flex items-center justify-between p-2">
          <span id="nav-title" className="sr-only">
            Navigation
          </span>
          <button
            onClick={() => setMobileNav(false)}
            aria-label="Close navigation"
            className="ml-auto rounded-md p-1.5 hover:bg-[var(--color-surface-muted)]"
          >
            <X className="size-4" />
          </button>
        </div>
        <SidebarContent onNavigate={() => setMobileNav(false)} />
      </Sheet>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}
