import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, fmt, when } from "../components/ui";
import { useReadings, useStations } from "../hooks/useApi";

const CHARTS: { title: string; unit: string; lines: [string, string, string][] }[] = [
  { title: "Motor speed", unit: "rpm", lines: [["motor_rpm", "motor rpm", "#38bdf8"], ["belt_speed", "belt speed ×11.25", "#a78bfa"]] },
  { title: "Hydraulic pressure", unit: "bar", lines: [["hydraulic_high_pressure", "high", "#f97316"], ["hydraulic_low_pressure", "low", "#22c55e"]] },
  { title: "Vibration", unit: "mm/s", lines: [["vibration", "vibration", "#ef4444"]] },
  { title: "Temperature", unit: "°C", lines: [["temperature", "temperature", "#f59e0b"]] },
  { title: "Motor current", unit: "A", lines: [["motor_current", "current", "#eab308"]] },
  { title: "Material load", unit: "t/h", lines: [["material_load", "load", "#14b8a6"]] },
];

export default function Stations() {
  const { data: st } = useStations();
  const [sel, setSel] = useState("ST-004"); const [hours, setHours] = useState(6);
  const { data } = useReadings(sel, hours);
  const pts = (data?.points ?? []).map(p => ({ ...p, belt_speed: p.belt_speed == null ? null : Number(p.belt_speed) * 11.25 }));
  const bad = pts.filter(p => p.data_quality_status !== "OK").length;
  return (
    <>
      <h1 className="text-xl font-semibold">Sensor Stations</h1>
      <div className="flex flex-wrap items-center gap-3">
        <select value={sel} onChange={e => setSel(e.target.value)} className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm">
          {st?.map(s => <option key={s.id} value={s.station_name}>{s.station_name} · {s.position_km.toFixed(1)} km · {s.status}</option>)}</select>
        <select value={hours} onChange={e => setHours(+e.target.value)} className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm">
          {[1, 3, 6, 12, 24].map(h => <option key={h} value={h}>last {h} h</option>)}</select>
        <span className="text-xs text-slate-400">time range is simulated time · {bad > 0 ? `${bad} buckets contain flagged data (missing/stuck/spike)` : "no data-quality flags in range"}</span>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {CHARTS.map(c => (
          <Card key={c.title} title={`${c.title} (${c.unit})`}>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={pts}><CartesianGrid stroke="#1e293b" /><XAxis dataKey="timestamp" tickFormatter={(t: string) => when(t).slice(7, 13)} tick={{ fill: "#94a3b8", fontSize: 10 }} minTickGap={40} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} width={40} /><Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} labelFormatter={(l: string) => when(l)} formatter={(v: number) => fmt(v, 2)} />
                {c.lines.length > 1 && <Legend />}
                {c.lines.map(([k, n, col]) => <Line key={k} type="monotone" dataKey={k} name={n} stroke={col} dot={false} strokeWidth={1.8} connectNulls={false} isAnimationActive={false} />)}</LineChart>
            </ResponsiveContainer>
          </Card>))}
      </div>
      <p className="text-xs text-slate-500">Gaps in a line = missing measurements (not interpolated in the charts). Belt speed is scaled ×11.25 to share the rpm axis.</p>
    </>
  );
}
