import { MarketIntelGrid } from "@/components/market-intel/MarketIntelGrid";
import { ForwardCurveChart } from "@/components/curve/ForwardCurveChart";
import { StoragePanel } from "@/components/storage/StoragePanel";
import { WeatherPanel } from "@/components/weather/WeatherPanel";
import { RiskSummaryCard } from "@/components/risk/RiskSummaryCard";
import { RecommendationsList } from "@/components/recommendations/RecommendationCard";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-4">
      <MarketIntelGrid />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <ForwardCurveChart instrument="NGZ26" />
        </div>
        <StoragePanel />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <WeatherPanel />
        <RiskSummaryCard />
      </div>
      <div>
        <h2 className="panel-title mb-2">AI Recommendations</h2>
        <RecommendationsList />
      </div>
    </div>
  );
}
