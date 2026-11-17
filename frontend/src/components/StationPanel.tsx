import { useStationHealth, useTrend } from "../hooks/useApi";
import { Badge, Card, fmt, when } from "./ui";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";

export function StationPanel({ name }: { name: string }) {
  const { data: h } = useStationHealth(name);
  const { data: tr } = useTrend(name);
  if (!h) return <Card title="Station">Loading…</Card>;
  const L = h.latest;
  const rows: [string, string][] = L ? [["Motor speed", `${fmt(L.motor_rpm)} rpm`], ["High pressure", `${fmt(L.hydraulic_high_pressure)} bar`], ["Low pressure", `${fmt(L.hydraulic_low_pressure)} bar`],
    ["Vibration", `${fmt(L.vibration, 2)} mm/s`], ["Temperature", `${fmt(L.temperature)} °C`], ["Motor current", `${fmt(L.motor_current)} A`], ["Material load", `${fmt(L.material_load, 0)} t/h`], ["Belt speed", `${fmt(L.belt_speed, 2)} m/s`]] : [];
  const p = h.latest_prediction;
  return (
    <Card title={`${h.station_name} · ${h.position_km.toFixed(1)} km`} right={<Badge v={h.status} />}>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs text-slate-400">Sensor reliability <Badge v={h.sensor_health} /> <span>quality (last 30): {Object.entries(h.data_quality_last_30).map(([k, v]) => `${k}×${v}`).join(", ")}</span></div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">{rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-slate-400">{k}</dt><dd className="text-right tabular-nums">{v}</dd></div>)}</dl>
          {L && <div className="mt-1 text-xs text-slate-500">latest reading {when(L.timestamp)}</div>}
        </div>
        <div className="space-y-3 text-sm">
          <div><div className="text-xs uppercase text-slate-400">Why this status</div>
            {h.evidence.length ? <ul className="list-disc pl-4">{h.evidence.map((e: any, i: number) => <li key={i}><span className="text-slate-400">{e.rule}:</span> {e.detail}</li>)}</ul> : <div className="text-slate-500">No active issue identified.</div>}</div>
          <div><div className="text-xs uppercase text-slate-400">Active anomalies</div>
            {h.active_anomalies.length ? h.active_anomalies.map((a: any) => <div key={a.id}><Badge v={a.severity} /> {a.type.replace(/_/g, " ")}</div>) : <div className="text-slate-500">None</div>}</div>
          <div><div className="text-xs uppercase text-slate-400">Latest failure-risk estimate</div>
            {p ? <div>{p.component} / {p.failure_type} — risk {fmt(p.risk_score, 2)} <Badge v={p.severity} />{p.estimated_time_to_failure_hours != null && ` · ~${fmt(p.estimated_time_to_failure_hours, 0)} h`}</div> : <div className="text-slate-500">–</div>}</div>
        </div>
      </div>
      {tr && tr.points.length > 1 && <div className="mt-3"><div className="text-xs uppercase text-slate-400">Risk-score trend (24 simulated h)</div>
        <ResponsiveContainer width="100%" height={90}><LineChart data={tr.points}><XAxis dataKey="t" hide /><YAxis domain={[0, 1]} width={28} tick={{ fill: "#94a3b8", fontSize: 10 }} /><Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} labelFormatter={(l: string) => when(l)} />
          <ReferenceLine y={0.5} stroke="#f59e0b" strokeDasharray="3 3" /><Line dataKey="risk" stroke="#ef4444" dot={false} strokeWidth={2} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>}
    </Card>
  );
}
