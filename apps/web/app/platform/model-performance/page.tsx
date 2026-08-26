import { HeaderBar } from "@/components/header/HeaderBar";
import { ModelPerformanceTable } from "@/components/model-performance/ModelPerformanceTable";

export default function ModelPerformancePage() {
  return (
    <div className="min-h-screen bg-terminal-bg text-terminal-text">
      <HeaderBar />
      <main className="p-4 max-w-3xl mx-auto">
        <ModelPerformanceTable />
      </main>
    </div>
  );
}
