import { NavLink, Outlet } from "react-router-dom";
import { Activity, AlertTriangle, Camera, Gauge, LayoutDashboard, Radio, SlidersHorizontal, TrendingDown } from "lucide-react";
import { useSim } from "../hooks/useApi";
import { when } from "./ui";

const NAV = [["/", "Overview", LayoutDashboard], ["/conveyor", "Conveyor Monitoring", Activity], ["/stations", "Sensor Stations", Gauge], ["/anomalies", "Anomalies", AlertTriangle],
  ["/predictions", "Failure Predictions", TrendingDown], ["/vision", "Vision Inspection", Camera], ["/simulation", "Simulation Controls", SlidersHorizontal]] as const;

export default function Layout() {
  const { data: sim, isError } = useSim();
  return (
    <div className="flex min-h-screen">
      <nav className="w-56 shrink-0 border-r border-slate-800 bg-slate-900 p-3">
        <div className="mb-4 px-2 text-sm font-bold text-slate-100">Conveyor Monitor<div className="text-xs font-normal text-slate-500">CV-001 · simulated</div></div>
        {NAV.map(([to, label, Icon]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `mb-1 flex items-center gap-2 rounded px-2 py-2 text-sm ${isActive ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}>
            <Icon size={16} />{label}</NavLink>))}
      </nav>
      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-between border-b border-slate-800 px-6 py-2 text-xs text-slate-400">
          <span className="flex items-center gap-2"><Radio size={14} className={sim?.running ? "text-green-400" : "text-slate-500"} />
            {isError ? "API unreachable - showing last data" : sim?.running ? `Simulation running ×${sim.speed}` : "Simulation paused"}</span>
          <span>{sim ? `Simulated time ${when(sim.simulated_time)}` : ""}</span>
        </header>
        <main className="space-y-4 p-6"><Outlet /></main>
      </div>
    </div>
  );
}
