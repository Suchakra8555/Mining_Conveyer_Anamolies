import type { Segment, Station } from "../types/api";
import { STATUS_COLOR } from "./ui";

/** Custom SVG conveyor: stations at their physical positions, damaged belt segments at their CURRENT (moving) positions. */
export function ConveyorMap({ stations, length, selected, onSelect, segments }: {
  stations: Station[]; length: number; selected: string | null; onSelect: (n: string) => void; segments?: Segment[];
}) {
  const W = 1000, pad = 40, y = 90, x = (m: number) => pad + (m / length) * (W - 2 * pad);
  return (
    <svg viewBox={`0 0 ${W} 190`} className="w-full" role="img" aria-label="Conveyor with sensor stations">
      <rect x={pad} y={y - 7} width={W - 2 * pad} height={14} rx={7} fill="#334155" />
      <rect x={pad} y={y + 26} width={W - 2 * pad} height={5} rx={2} fill="#1e293b" />
      <text x={pad} y={y + 46} fill="#64748b" fontSize="11">return strand (continuous loop: position = travelled distance mod length)</text>
      {[0, 1, 2, 3, 4, 5].map(i => <g key={i}><line x1={x(i * length / 5)} x2={x(i * length / 5)} y1={y + 8} y2={y + 12} stroke="#64748b" /><text x={x(i * length / 5)} y={y + 66} textAnchor="middle" fill="#64748b" fontSize="11">{(i * length / 5000).toFixed(0)} km</text></g>)}
      {segments?.map(s => <g key={s.id}><title>{`${s.id} health ${s.segment_health}`}</title><rect x={x(s.position_meters) - 3} y={y + 20} width={6} height={18} fill={s.segment_health < 0.5 ? "#ef4444" : "#f59e0b"} /></g>)}
      <polygon points={`${x(0)},${y - 24} ${x(0) - 6},${y - 36} ${x(0) + 6},${y - 36}`} fill="#38bdf8"><title>Camera position (simulated)</title></polygon>
      {stations.map(s => {
        const c = STATUS_COLOR[s.status] ?? "#6b7280", sel = selected === s.station_name;
        return (
          <g key={s.id} onClick={() => onSelect(s.station_name)} className="cursor-pointer" tabIndex={0} role="button" aria-label={`${s.station_name} ${s.status}`}
             onKeyDown={e => e.key === "Enter" && onSelect(s.station_name)}>
            <line x1={x(s.position_meters)} x2={x(s.position_meters)} y1={y - 38} y2={y - 8} stroke={c} strokeWidth={2} />
            <circle cx={x(s.position_meters)} cy={y - 46} r={sel ? 13 : 10} fill={c} stroke={sel ? "#fff" : "#0f172a"} strokeWidth={sel ? 3 : 2} />
            <text x={x(s.position_meters)} y={y - 68} textAnchor="middle" fill="#cbd5e1" fontSize="12" fontWeight={sel ? 700 : 400}>{s.station_name}</text>
            <text x={x(s.position_meters)} y={y - 82} textAnchor="middle" fill="#64748b" fontSize="10">{s.position_km.toFixed(1)} km</text>
          </g>
        );
      })}
    </svg>
  );
}

export const Legend = () => (
  <div className="flex flex-wrap gap-4 text-xs text-slate-400">
    {[["Normal", "#22c55e"], ["Abnormal", "#f59e0b"], ["Predicted failure", "#ef4444"], ["Offline / unknown", "#6b7280"]].map(([l, c]) =>
      <span key={l} className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full" style={{ background: c }} />{l}</span>)}
    <span className="flex items-center gap-1"><span className="inline-block h-3 w-1.5 bg-amber-500" />damaged belt segment</span>
  </div>
);
