import { useState } from "react";
import { ConveyorMap, Legend } from "../components/ConveyorMap";
import { StationPanel } from "../components/StationPanel";
import { Card, Note } from "../components/ui";
import { useSegments, useStations } from "../hooks/useApi";

export default function Conveyor() {
  const { data: st } = useStations(); const { data: seg } = useSegments();
  const [sel, setSel] = useState<string | null>("ST-004");
  return (
    <>
      <h1 className="text-xl font-semibold">Conveyor Monitoring</h1>
      <Card title="Station map (5 km)" right={<Legend />}>
        {st && <ConveyorMap stations={st} length={5000} selected={sel} onSelect={setSel} segments={seg?.segments} />}
        {seg && <p className="text-xs text-slate-400">Belt travelled {seg.tracker.traveled_m.toLocaleString()} m ({seg.tracker.loops} loops); segment under camera: {seg.tracker.segment_under_camera}.</p>}
      </Card>
      <Note>Damaged belt-segment markers move with the belt (position = origin + travelled distance mod length). Segment positions are simulated metadata, not read from images.</Note>
      {sel && <StationPanel name={sel} />}
    </>
  );
}
