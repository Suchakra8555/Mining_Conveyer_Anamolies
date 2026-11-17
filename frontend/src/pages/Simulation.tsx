import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, Note, when } from "../components/ui";
import { useScenarios, useSim, useStations } from "../hooks/useApi";
import { api } from "../services/api";

const PRESETS: { label: string; steps: { type: string; station_id: string; kind: string; duration: number; channel?: string }[] }[] = [
  { label: "Bearing wear at ST-006", steps: [{ type: "degradation", station_id: "ST-006", kind: "bearing_degradation", duration: 10 }] },
  { label: "Belt slippage at ST-005", steps: [{ type: "anomaly", station_id: "ST-005", kind: "BELT_SLIPPAGE", duration: 7200 }] },
  { label: "Unexpected stop at ST-007", steps: [{ type: "anomaly", station_id: "ST-007", kind: "UNEXPECTED_STOP", duration: 0 }] },
  { label: "Sensor disconnect at ST-009 (not equipment failure)", steps: [{ type: "anomaly", station_id: "ST-009", kind: "SENSOR_DISCONNECT", duration: 5400 }] },
];

export default function Simulation() {
  const { data: sim } = useSim(); const { data: sc } = useScenarios(); const { data: st } = useStations();
  const qc = useQueryClient();
  const [type, setType] = useState("anomaly"); const [kind, setKind] = useState("MOTOR_OVERLOAD"); const [station, setStation] = useState("ST-003");
  const [dur, setDur] = useState(3600); const [msg, setMsg] = useState("");
  const refresh = () => qc.invalidateQueries();
  const act = async (fn: () => Promise<any>, ok: string) => { try { await fn(); setMsg(ok); } catch (e) { setMsg(String(e)); } refresh(); };
  const kinds = type === "anomaly" ? [...(sc?.anomalies.cycle_structure ?? []), ...(sc?.anomalies.value_level ?? []), ...(sc?.anomalies.sensor_faults ?? [])] : Object.keys(sc?.degradations ?? {});
  const inject = (b: any) => act(() => api.post("/api/simulation/scenarios", b), `Injected ${b.kind} at ${b.station_id}`);
  return (
    <>
      <h1 className="text-xl font-semibold">Simulation Controls</h1>
      <Card title="Run control">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => act(() => api.post("/api/simulation/start"), "started")} disabled={sim?.running}>Start</Button>
          <Button onClick={() => act(() => api.post("/api/simulation/stop"), "stopped")} disabled={!sim?.running}>Stop</Button>
          <Button onClick={() => act(() => api.post("/api/simulation/step?n=10"), "advanced 10 ticks")}>Step ×10</Button>
          <Button onClick={() => confirm("Reset wipes the database and regenerates 12 h of history. Continue?") && act(() => api.post("/api/simulation/reset", { warm_start_hours: 12 }), "reset done")}>Reset</Button>
          <label className="ml-4 text-sm">Speed <select className="rounded border border-slate-600 bg-slate-800 px-2 py-1" value={sim?.speed ?? 30} onChange={e => act(() => api.post("/api/simulation/speed", { speed: +e.target.value }), "speed changed")}>
            {[1, 10, 30, 60, 120, 300].map(s => <option key={s} value={s}>×{s} ({s * 2} simulated s per 2 s tick)</option>)}</select></label>
        </div>
        <p className="mt-2 text-xs text-slate-400">{sim ? `tick ${sim.tick} · simulated time ${when(sim.simulated_time)} · seed ${sim.seed} · belt travelled ${sim.belt.traveled_m.toLocaleString()} m` : ""} {msg && <b className="ml-2 text-sky-300">{msg}</b>}</p>
      </Card>
      <Card title="Predefined scenarios"><div className="flex flex-wrap gap-2">{PRESETS.map(p => <Button key={p.label} onClick={() => p.steps.forEach(s => inject(s))}>{p.label}</Button>)}</div>
        <p className="mt-2 text-xs text-slate-400">Effects appear after the next inference run (every 5 ticks). Degradations ramp up over the chosen hours of simulated time.</p></Card>
      <Card title="Inject manually">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label>Type<select className="ml-2 rounded border border-slate-600 bg-slate-800 px-2 py-1" value={type} onChange={e => { setType(e.target.value); setKind(e.target.value === "anomaly" ? "MOTOR_OVERLOAD" : "bearing_degradation"); setDur(e.target.value === "anomaly" ? 3600 : 10); }}><option value="anomaly">abnormal condition</option><option value="degradation">component degradation</option></select></label>
          <label>Station<select className="ml-2 rounded border border-slate-600 bg-slate-800 px-2 py-1" value={station} onChange={e => setStation(e.target.value)}>{st?.map(s => <option key={s.id}>{s.station_name}</option>)}</select></label>
          <label>Kind<select className="ml-2 rounded border border-slate-600 bg-slate-800 px-2 py-1" value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(k => <option key={k}>{k}</option>)}</select></label>
          <label>{type === "anomaly" ? "Duration (s)" : "Hours to failure"}<input type="number" min={1} className="ml-2 w-24 rounded border border-slate-600 bg-slate-800 px-2 py-1" value={dur} onChange={e => setDur(+e.target.value)} /></label>
          <Button onClick={() => inject({ type, station_id: station, kind, duration: dur })}>Inject</Button>
        </div>
      </Card>
      <Note>Sensor faults (SENSOR_*) test the data-quality path: the station turns grey (offline/unknown) rather than raising an equipment anomaly.</Note>
      <Card title="Station operating modes (simulator internal state)"><div className="flex flex-wrap gap-2 text-xs">{sim && Object.entries(sim.station_modes).map(([k, v]) => <span key={k} className="rounded border border-slate-700 px-2 py-1">{k}: {v}</span>)}</div></Card>
    </>
  );
}
