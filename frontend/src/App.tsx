import { TooltipProvider } from "@/components/ui/tooltip";
import { WarehouseRuntimeProvider } from "@/lib/chat-runtime";
import { Thread } from "@/components/assistant-ui/thread";

export default function App() {
  return (
    <TooltipProvider>
      <WarehouseRuntimeProvider>
        <Thread />
      </WarehouseRuntimeProvider>
    </TooltipProvider>
  );
}
