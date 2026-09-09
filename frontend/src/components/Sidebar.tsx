import { NavLink, useNavigate } from "react-router-dom";
import { MessageSquarePlus, Compass, GitCompare, Info, Trash2, Building2 } from "lucide-react";
import { useChat, useCompare } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const NAV = [
  { to: "/", label: "Chat", icon: MessageSquarePlus, end: true },
  { to: "/explore", label: "Explore", icon: Compass },
  { to: "/compare", label: "Compare", icon: GitCompare },
  { to: "/sources", label: "Sources & About", icon: Info },
];

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { conversations, activeId, newConversation, setActive, clearAll } = useChat();
  const compareCount = useCompare((s) => s.ids.length);
  const navigate = useNavigate();

  return (
    <div className="flex h-full w-full flex-col gap-3 p-3">
      <div className="flex items-center gap-2 px-1 pt-1">
        <div className="flex size-7 items-center justify-center rounded-lg bg-[var(--color-accent)] text-white">
          <Building2 className="size-4" />
        </div>
        <span className="font-semibold tracking-tight">EstateLens</span>
      </div>

      <Button
        variant="outline"
        className="justify-start"
        onClick={() => {
          newConversation();
          navigate("/");
          onNavigate?.();
        }}
      >
        <MessageSquarePlus /> New conversation
      </Button>

      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 rounded-[10px] px-2.5 py-2 text-sm transition-colors",
                isActive
                  ? "bg-[var(--color-surface-muted)] font-medium text-[var(--color-ink)]"
                  : "text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-muted)]",
              )
            }
          >
            <Icon className="size-4" />
            {label}
            {to === "/compare" && compareCount > 0 && (
              <span className="ml-auto rounded-full bg-[var(--color-accent)] px-1.5 text-[11px] font-semibold text-white">
                {compareCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-1 flex items-center justify-between px-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-soft)]">
          Recent
        </span>
        {conversations.length > 0 && (
          <button
            onClick={() => {
              if (confirm("Delete all local conversations? This cannot be undone.")) clearAll();
            }}
            className="inline-flex items-center gap-1 text-[11px] text-[var(--color-ink-soft)] hover:text-[#8a2b21]"
          >
            <Trash2 className="size-3" /> Clear
          </button>
        )}
      </div>

      <div className="-mr-1 flex-1 overflow-y-auto pr-1">
        {conversations.length === 0 ? (
          <p className="px-1 text-xs text-[var(--color-ink-soft)]">
            Conversations are stored only in this browser.
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => {
                    setActive(c.id);
                    navigate("/");
                    onNavigate?.();
                  }}
                  className={cn(
                    "line-clamp-1 w-full rounded-[8px] px-2.5 py-1.5 text-left text-[13px] transition-colors",
                    activeId === c.id
                      ? "bg-[var(--color-surface-muted)] text-[var(--color-ink)]"
                      : "text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-muted)]",
                  )}
                >
                  {c.title}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="px-1 text-[11px] leading-relaxed text-[var(--color-ink-soft)]">
        Independent demo. Data collected from public DarGlobal &amp; Wasalt pages; not affiliated
        with either.
      </p>
    </div>
  );
}
