/* assistant-ui runtime adapter — connects our SSE backend to useLocalRuntime */
"use client";

import type { ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";

/* Generate stable session id per mount */
function makeSessionId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

const sessionId = makeSessionId();

const WarehouseModelAdapter: ChatModelAdapter = {
  async run({ messages, abortSignal }) {
    // Get the last user message
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

    return {
      content: [{ type: "text", text: fullAnswer || "(no response)" }],
    };
  },
};

export function WarehouseRuntimeProvider({
  children,
}: {
  children: ReactNode;
}) {
  const runtime = useLocalRuntime(WarehouseModelAdapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
