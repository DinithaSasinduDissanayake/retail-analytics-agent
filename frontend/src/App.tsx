import { useCallback, useEffect, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  makeSessionId,
  WarehouseRuntimeProvider,
  type ChatSession,
} from "@/lib/chat-runtime";
import { Thread } from "@/components/assistant-ui/thread";
import DashboardPage from "@/components/DashboardPage";
import { Sidebar, type ActiveView } from "@/components/Sidebar";

const STORAGE_KEY = "retail-analytics-chats-v1";

function loadChats(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export default function App() {
  const [collapsed, setCollapsed] = useState(false);
  const [activeView, setActiveView] = useState<ActiveView>("chat");
  const [chats, setChats] = useState<ChatSession[]>(() => loadChats());
  const [activeChatId, setActiveChatId] = useState<string>(() => makeSessionId());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
    } catch {
      // Ignore storage quota errors
    }
  }, [chats]);

  const activeChat = chats.find((c) => c.id === activeChatId);

  const handleNewChat = useCallback(() => {
    setActiveChatId(makeSessionId());
    setActiveView("chat");
  }, []);

  const handleSelectChat = useCallback((id: string) => {
    setActiveChatId(id);
    setActiveView("chat");
  }, []);

  const handleDeleteChat = useCallback(
    (id: string) => {
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (id === activeChatId) {
        setActiveChatId(makeSessionId());
      }
    },
    [activeChatId],
  );

  const handleExchangeComplete = useCallback(
    (sessionId: string, userText: string, assistantText: string) => {
      setChats((prev) => {
        const existing = prev.find((c) => c.id === sessionId);
        const title =
          userText.trim().slice(0, 44) + (userText.trim().length > 44 ? "…" : "");

        if (existing) {
          const updated: ChatSession = {
            ...existing,
            updatedAt: Date.now(),
            messages: [
              ...existing.messages,
              { role: "user", text: userText },
              { role: "assistant", text: assistantText },
            ],
          };
          return [updated, ...prev.filter((c) => c.id !== sessionId)];
        }

        const created: ChatSession = {
          id: sessionId,
          title: title || "New chat",
          updatedAt: Date.now(),
          messages: [
            { role: "user", text: userText },
            { role: "assistant", text: assistantText },
          ],
        };
        return [created, ...prev];
      });
    },
    [],
  );

  return (
    <TooltipProvider>
      <div className="flex h-screen w-screen overflow-hidden bg-white dark:bg-[#212121]">
        <Sidebar
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((c) => !c)}
          activeView={activeView}
          onSelectView={setActiveView}
          chats={chats}
          activeChatId={activeChatId}
          onNewChat={handleNewChat}
          onSelectChat={handleSelectChat}
          onDeleteChat={handleDeleteChat}
        />

        <main className="relative flex-1 min-w-0 h-full overflow-hidden">
          {activeView === "dashboard" ? (
            <DashboardPage />
          ) : (
            <WarehouseRuntimeProvider
              key={activeChatId}
              sessionId={activeChatId}
              initialMessages={activeChat?.messages ?? []}
              onExchangeComplete={handleExchangeComplete}
            >
              <Thread />
            </WarehouseRuntimeProvider>
          )}
        </main>
      </div>
    </TooltipProvider>
  );
}
