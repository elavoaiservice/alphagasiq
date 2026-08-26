import { HeaderBar } from "@/components/header/HeaderBar";
import { ChatPanel } from "@/components/chat/ChatPanel";

export default function ChatPage() {
  return (
    <div className="min-h-screen bg-terminal-bg text-terminal-text">
      <HeaderBar />
      <main className="p-4 max-w-3xl mx-auto">
        <ChatPanel />
      </main>
    </div>
  );
}
