import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Note, when } from "../components/ui";
import { useDetections, useSegments, useVisionInfo } from "../hooks/useApi";
import { api } from "../services/api";
import type { Detection } from "../types/api";

export default function Vision() {
  const { data: det } = useDetections(); const { data: seg } = useSegments(); const { data: info } = useVisionInfo();
  const [sel, setSel] = useState<Detection | null>(null); const [msg, setMsg] = useState(""); const file = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const upload = async () => {
    const f = file.current?.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api.analyze(fd); setMsg(`${r.detections.length} detection(s) on segment ${r.segment_id} (${r.location_source})`); qc.invalidateQueries({ queryKey: ["detections"] }); } catch (e) { setMsg(String(e)); }
  };
  const cur = sel ?? det?.items[0] ?? null;
  return (
    <>
      <h1 className="text-xl font-semibold">Vision Inspection</h1>
      <Note><b>Demo detector, not a validated model.</b> {info ? `Detector: ${info.detector_kind} (validated: ${String(info.validated)}). ` : ""}Images are procedurally generated <i>synthetic</i> belt images; no public defect dataset or pretrained conveyor weights could be downloaded in the build environment. Belt segment and position are <b>simulated metadata</b>.</Note>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Selected incident" className="lg:col-span-2">
          {cur ? <div className="grid gap-3 md:grid-cols-2">
            <figure><img src={api.file(cur.image_path)} className="w-full rounded border border-slate-700" alt="original belt image" /><figcaption className="mt-1 text-xs text-slate-400">Original</figcaption></figure>
            <figure>{cur.annotated_path ? <img src={api.file(cur.annotated_path)} className="w-full rounded border border-slate-700" alt="annotated" /> : <div className="p-6 text-slate-500">no annotated image</div>}<figcaption className="mt-1 text-xs text-slate-400">Annotated (latest observation image)</figcaption></figure>
            <dl className="col-span-full grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-4">
              <div><dt className="text-xs text-slate-400">Damage</dt><dd>{cur.damage_type.replace(/_/g, " ")}</dd></div>
              <div><dt className="text-xs text-slate-400">Score ({cur.detector_kind})</dt><dd>{cur.confidence.toFixed(2)}</dd></div>
              <div><dt className="text-xs text-slate-400">Belt segment</dt><dd>{cur.belt_segment_id ?? "unknown"}</dd></div>
              <div><dt className="text-xs text-slate-400">Position at detection</dt><dd>{cur.belt_position != null ? `${cur.belt_position.toFixed(0)} m (${cur.location_source})` : "unknown"}</dd></div>
              <div><dt className="text-xs text-slate-400">Observations</dt><dd>{cur.observation_count} (one incident)</dd></div>
              <div><dt className="text-xs text-slate-400">Size change</dt><dd>{cur.growth_ratio ? `×${cur.growth_ratio} since first sighting` : "–"}</dd></div>
              <div><dt className="text-xs text-slate-400">First seen</dt><dd>{when(cur.detected_at)}</dd></div>
              <div className="col-span-2 text-xs text-slate-500 md:col-span-4">{cur.confidence_meaning}</div>
            </dl></div> : <div className="text-slate-500">No detections yet.</div>}
        </Card>
        <Card title="Analyse an image">
          <input ref={file} type="file" accept="image/*" className="block w-full text-xs" />
          <Button className="mt-2" onClick={upload}>Analyse</Button>
          <p className="mt-2 text-xs text-slate-400">{msg || "Uploads are assigned to the belt segment currently under the simulated camera."}</p>
          {info && <div className="mt-3 text-xs text-slate-400">Supported classes: {info.supported_classes.join(", ")}</div>}
        </Card>
      </div>
      <Card title={`Detection history — one row per physical defect (${det?.total ?? 0})`}>
        <table className="w-full text-left text-sm"><thead className="text-xs uppercase text-slate-400"><tr><th className="p-2">Segment</th><th>Damage</th><th>Score</th><th>Observations</th><th>Growth</th><th>Location</th><th>First seen</th></tr></thead>
          <tbody>{det?.items.map(d => (
            <tr key={d.id} onClick={() => setSel(d)} className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800/60 ${cur?.id === d.id ? "bg-slate-800" : ""}`}>
              <td className="p-2">{d.belt_segment_id}</td><td>{d.damage_type.replace(/_/g, " ")}</td><td>{d.confidence.toFixed(2)}</td><td>{d.observation_count}</td><td>{d.growth_ratio ? `×${d.growth_ratio}` : "–"}</td><td><Badge v={d.location_source === "SIMULATED" ? "UNKNOWN" : "LOW"}>{d.location_source}</Badge></td><td>{when(d.detected_at)}</td></tr>))}</tbody></table>
      </Card>
      <Card title="Damaged belt segments">
        <div className="flex flex-wrap gap-2 text-sm">{seg?.segments.map(s => <span key={s.id} className="rounded border border-slate-700 px-2 py-1">{s.id} · health {s.segment_health} · {s.position_meters.toFixed(0)} m · {s.pass_count} passes</span>)}</div>
      </Card>
    </>
  );
}
