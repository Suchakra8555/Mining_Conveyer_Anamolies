import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";
import { Badge, Card, Note, when } from "../components/ui";
import { usePredictions, useTrend } from "../hooks/useApi";

function Trend({ st }: { st: string }) {
  const { data } = useTrend(st);
  if (!data || data.points.length < 2) return <span className="text-xs text-slate-500">no history</span>;
  return <ResponsiveContainer width={180} height={46}><LineChart data={data.points}><XAxis dataKey="t" hide /><YAxis domain={[0, 1]} hide /><ReferenceLine y={0.5} stroke="#475569" strokeDasharray="2 2" />
    <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} labelFormatter={(l: string) => when(l)} /><Line dataKey="risk" stroke="#ef4444" dot={false} strokeWidth={2} isAnimationActive={false} /></LineChart></ResponsiveContainer>;
}

export default function Predictions() {
  const { data } = usePredictions();
  return (
    <>
      <h1 className="text-xl font-semibold">Failure Predictions</h1>
      <Note>Risk score = 1 − P(no fault) from a model trained only on <b>simulated degradation scenarios</b>. It is a ranking score, not a calibrated probability. Time-to-failure is only shown when the risk is above 0.5 and is relative to the simulator’s failure trajectories.</Note>
      <Card>
        <table className="w-full text-left text-sm"><thead className="text-xs uppercase text-slate-400"><tr><th className="p-2">Location</th><th>Component</th><th>Predicted fault</th><th>Risk</th><th>Severity</th><th>Est. time to failure</th><th>Degradation trend (24 h)</th></tr></thead>
          <tbody>{data?.items.map(p => (
            <tr key={p.id} className="border-t border-slate-800"><td className="p-2">{p.station_name} · {(p.position_meters / 1000).toFixed(1)} km</td><td>{p.component.replace(/_/g, " ")}</td><td>{p.failure_type.replace(/_/g, " ")}</td>
              <td className="tabular-nums">{p.risk_score.toFixed(2)}</td><td><Badge v={p.severity} /></td><td>{p.estimated_time_to_failure_hours != null ? `~${p.estimated_time_to_failure_hours.toFixed(0)} h` : "not available"}</td><td><Trend st={p.station_name} /></td></tr>))}
            {data && data.items.length === 0 && <tr><td colSpan={7} className="p-4 text-slate-500">No elevated failure risk right now.</td></tr>}</tbody></table>
        <div className="mt-2 text-xs text-slate-500">Basis: SIMULATED_DEGRADATION</div>
      </Card>
    </>
  );
}
