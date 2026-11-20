/* assistant-ui runtime adapter — connects our SSE backend to useLocalRuntime */
"use client";

import { useMemo, type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadMessageLike,
} from "@assistant-ui/react";

export interface StoredMessage {
  role: "user" | "assistant";
  text: string;
}

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredMessage[];
}

export function makeSessionId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function WarehouseRuntimeProvider({
  sessionId,
  initialMessages = [],
  onExchangeComplete,
  children,
}: {
  sessionId: string;
  initialMessages?: StoredMessage[];
  onExchangeComplete?: (sessionId: string, userText: string, assistantText: string) => void;
  children: ReactNode;
}) {
  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async run({ messages, abortSignal }) {
        const lastMsg = [...messages].reverse().find((m) => m.role === "user");
        const query = lastMsg
          ? lastMsg.content
              .filter((p) => p.type === "text")
              .map((p) => (p as { text: string }).text)
              .join("\n")
          : "";

        if (!query) {
          return { content: [] };
        }

        const response = await fetch("/api/agent/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: query, session_id: sessionId }),
          signal: abortSignal,
        });

        if (!response.ok) {
          throw new Error(`Server error: ${response.status}`);
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullAnswer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;

            let event: Record<string, unknown>;
            try {
              event = JSON.parse(raw);
            } catch {
              continue;
            }

            switch (event.type) {
              case "done":
                fullAnswer = String(event.answer || "");
                break;
              case "error":
                throw new Error(String(event.message || "Agent error"));
            }
          }
        }

        const finalText = fullAnswer || "(no response)";
        onExchangeComplete?.(sessionId, query, finalText);

        return {
          content: [{ type: "text", text: finalText }],
        };
      },
    }),
    [sessionId, onExchangeComplete],
  );

  const mappedInitial = useMemo<ThreadMessageLike[]>(
    () =>
      initialMessages.map((m) => ({
        role: m.role,
        content: [{ type: "text", text: m.text }],
      })),
    // Only seed initialMessages on mount (component is keyed by sessionId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const runtime = useLocalRuntime(adapter, { initialMessages: mappedInitial });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
