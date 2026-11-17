import { useState } from "react";
import { Link } from "react-router-dom";
import { ConveyorMap, Legend } from "../components/ConveyorMap";
import { StationPanel } from "../components/StationPanel";
import { Badge, Card, Stat, when } from "../components/ui";
import { useAnomalies, usePredictions, useSegments, useStations, useSummary } from "../hooks/useApi";

export default function Overview() {
  const { data: s } = useSummary(); const { data: st } = useStations(); const { data: seg } = useSegments();
  const { data: an } = useAnomalies("status=ACTIVE&limit=8"); const { data: pr } = usePredictions();
  const [sel, setSel] = useState<string | null>(null);
  return (
    <>
      <h1 className="text-xl font-semibold">Overview</h1>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Conveyor" value={s?.conveyor_status ?? "–"} tone={s?.conveyor_status === "RUNNING" ? "text-green-400" : "text-slate-300"} />
        <Stat label="Length" value={s ? `${s.conveyor_length_m / 1000} km` : "–"} />
        <Stat label="Stations" value={s?.total_stations ?? "–"} />
        <Stat label="Healthy" value={s?.healthy_stations ?? "–"} tone="text-green-400" />
        <Stat label="Abnormal" value={s?.abnormal_stations ?? "–"} tone="text-amber-400" />
        <Stat label="Predicted failure" value={s?.predicted_failure_stations ?? "–"} tone="text-red-400" />
        <Stat label="Active anomalies" value={s?.active_anomalies ?? "–"} tone="text-amber-400" />
        <Stat label="Critical alerts" value={s?.critical_alerts ?? "–"} tone="text-red-400" />
      </div>
      <Card title="Conveyor — click a station" right={<Legend />}>
        {st && <ConveyorMap stations={st} length={s?.conveyor_length_m ?? 5000} selected={sel} onSelect={setSel} segments={seg?.segments} />}
        {s && (s.offline_stations > 0 || s.unknown_stations > 0) && <p className="mt-1 text-xs text-slate-500">{s.offline_stations} offline, {s.unknown_stations} unknown: sensor availability problems are shown grey, never as healthy.</p>}
      </Card>
      {sel && <StationPanel name={sel} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Active anomalies" right={<Link className="text-xs text-sky-400" to="/anomalies">all →</Link>}>
          <ul className="space-y-2 text-sm">{an?.items.map(a => <li key={a.id}><Badge v={a.severity} /> <b>{a.station_name}</b> ({(a.position_meters / 1000).toFixed(1)} km) {a.anomaly_type.replace(/_/g, " ")} <span className="text-xs text-slate-500">{when(a.detected_at)}</span></li>)}
            {an && an.items.length === 0 && <li className="text-slate-500">No active anomalies.</li>}</ul>
        </Card>
        <Card title="Predicted failures" right={<Link className="text-xs text-sky-400" to="/predictions">all →</Link>}>
          <ul className="space-y-2 text-sm">{pr?.items.map(p => <li key={p.id}><Badge v={p.severity} /> <b>{p.station_name}</b> {p.component.replace(/_/g, " ")} — risk {p.risk_score.toFixed(2)}{p.estimated_time_to_failure_hours != null && `, ~${p.estimated_time_to_failure_hours.toFixed(0)} h`}</li>)}
            {pr && pr.items.length === 0 && <li className="text-slate-500">No elevated failure risk.</li>}</ul>
        </Card>
      </div>
    </>
  );
}
