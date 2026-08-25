import { HeaderBar } from "@/components/header/HeaderBar";
import { PipelineMap } from "@/components/pipeline-map/PipelineMap";

export default function PipelineMapPage() {
  return (
    <div className="min-h-screen bg-terminal-bg text-terminal-text">
      <HeaderBar />
      <main className="p-4">
        <PipelineMap />
      </main>
    </div>
  );
}
