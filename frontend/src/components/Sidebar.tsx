import {
  Database,
  LayoutDashboard,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2,
} from "lucide-react";
import type { ChatSession } from "@/lib/chat-runtime";

export type ActiveView = "chat" | "dashboard";

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  activeView: ActiveView;
  onSelectView: (view: ActiveView) => void;
  chats: ChatSession[];
  activeChatId: string;
  onNewChat: () => void;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
}

export function Sidebar({
  collapsed,
  onToggleCollapse,
  activeView,
  onSelectView,
  chats,
  activeChatId,
  onNewChat,
  onSelectChat,
  onDeleteChat,
}: SidebarProps) {
  if (collapsed) {
    return (
      <div className="fixed left-3 top-3 z-30 flex items-center gap-1.5">
        <button
          type="button"
          onClick={onToggleCollapse}
          title="Open sidebar"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-[#171717]/90 text-[#ececec] backdrop-blur hover:bg-[#2a2a2a] transition-colors cursor-pointer"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onNewChat}
          title="New chat"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-[#171717]/90 text-[#ececec] backdrop-blur hover:bg-[#2a2a2a] transition-colors cursor-pointer"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-white/10 bg-[#171717] text-[#ececec] select-none">
      {/* Brand Header */}
      <div className="flex items-center justify-between px-3.5 pt-3.5 pb-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[#ececec]">
            <Database className="h-4 w-4" />
          </div>
          <span className="truncate text-sm font-semibold tracking-tight text-[#ececec]">
            Retail Analytics
          </span>
        </div>
        <button
          type="button"
          onClick={onToggleCollapse}
          title="Collapse sidebar"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-[#a8a8a8] hover:bg-white/10 hover:text-[#ececec] transition-colors cursor-pointer"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* Primary Actions */}
      <div className="space-y-1 px-2.5 py-2">
        <button
          type="button"
          onClick={onNewChat}
          className="flex w-full items-center gap-2.5 rounded-lg bg-white/10 px-3 py-2 text-sm font-medium text-[#ececec] hover:bg-white/15 transition-colors cursor-pointer"
        >
          <Plus className="h-4 w-4" />
          <span>New chat</span>
        </button>

        <button
          type="button"
          onClick={() => onSelectView("chat")}
          className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors cursor-pointer ${
            activeView === "chat"
              ? "bg-white/8 text-[#ececec] font-medium"
              : "text-[#a8a8a8] hover:bg-white/5 hover:text-[#ececec]"
          }`}
        >
          <MessageSquare className="h-4 w-4" />
          <span>Chat Agent</span>
        </button>

        <button
          type="button"
          onClick={() => onSelectView("dashboard")}
          className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors cursor-pointer ${
            activeView === "dashboard"
              ? "bg-white/8 text-[#ececec] font-medium"
              : "text-[#a8a8a8] hover:bg-white/5 hover:text-[#ececec]"
          }`}
        >
          <LayoutDashboard className="h-4 w-4" />
          <span>SQL Dashboard</span>
        </button>
      </div>

      {/* Recents List */}
      <div className="mt-2 flex-1 overflow-y-auto px-2.5">
        <div className="px-2.5 pb-1.5 text-xs font-medium text-[#8e8e8e]">
          Recents
        </div>
        {chats.length === 0 ? (
          <div className="px-2.5 py-2 text-xs text-[#6e6e6e]">
            No previous chats yet.
          </div>
        ) : (
          <div className="space-y-0.5">
            {chats.map((chat) => {
              const isActive = activeView === "chat" && chat.id === activeChatId;
              return (
                <div
                  key={chat.id}
                  onClick={() => onSelectChat(chat.id)}
                  className={`group flex items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-sm cursor-pointer transition-colors ${
                    isActive
                      ? "bg-white/12 text-[#ececec]"
                      : "text-[#c4c4c4] hover:bg-white/6 hover:text-[#ececec]"
                  }`}
                >
                  <span className="truncate">{chat.title}</span>
                  <button
                    type="button"
                    title="Delete chat"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteChat(chat.id);
                    }}
                    className="shrink-0 opacity-0 group-hover:opacity-100 text-[#8e8e8e] hover:text-red-400 transition-opacity cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-white/10 px-3.5 py-3 text-xs text-[#8e8e8e] flex items-center justify-between">
        <span>DuckDB OLAP</span>
        <span className="rounded bg-white/8 px-1.5 py-0.5 text-[11px] text-[#b4b4b4]">
          Read-Only
        </span>
      </div>
    </aside>
  );
}
