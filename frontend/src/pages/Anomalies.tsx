import { useState } from "react";
import { Badge, Card, Note, when } from "../components/ui";
import { useAnomalies } from "../hooks/useApi";

const SRC: Record<string, string> = { PAPER_APPROACH_2: "Research Approach 2 (duty cycle)", SIGNAL_RULE: "Rule check (our extension)" };

export default function Anomalies() {
  const [status, setStatus] = useState("ACTIVE");
  const { data } = useAnomalies(`${status ? `status=${status}&` : ""}limit=100`);
  return (
    <>
      <h1 className="text-xl font-semibold">Anomalies</h1>
      <Note>Anomalies are abnormal <b>operating behaviour</b>, not confirmed physical failures. Sensor faults (missing, stuck, spikes) are tracked separately as sensor reliability and are never raised as equipment anomalies.</Note>
      <select value={status} onChange={e => setStatus(e.target.value)} className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm">
        <option value="ACTIVE">Active</option><option value="RESOLVED">Resolved</option><option value="">All</option></select>
      <Card>
        <table className="w-full text-left text-sm"><thead className="text-xs uppercase text-slate-400"><tr><th className="p-2">Severity</th><th>Type</th><th>Location</th><th>Detected (sim time)</th><th>Source</th><th>Details / measurements</th><th>Status</th></tr></thead>
          <tbody>{data?.items.map(a => (
            <tr key={a.id} className="border-t border-slate-800 align-top"><td className="p-2"><Badge v={a.severity} /></td><td>{a.anomaly_type.replace(/_/g, " ")}</td>
              <td>{a.station_name} · {(a.position_meters / 1000).toFixed(1)} km</td><td>{when(a.detected_at)}</td><td className="text-xs">{SRC[a.source] ?? a.source}</td>
              <td className="max-w-md text-xs text-slate-400">{a.description}</td><td><Badge v={a.status} /></td></tr>))}
            {data && data.items.length === 0 && <tr><td colSpan={7} className="p-4 text-slate-500">Nothing to show.</td></tr>}</tbody></table>
        {data && <div className="mt-2 text-xs text-slate-500">{data.total} total</div>}
      </Card>
    </>
  );
}
