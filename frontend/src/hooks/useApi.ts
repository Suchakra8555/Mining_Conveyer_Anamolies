import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";
import type { Anomaly, Detection, Page, Prediction, Scenarios, Segment, SimStatus, Station, Summary, Point } from "../types/api";

const POLL = 2500; // ms - polling (no websockets): dashboard keeps last data if a poll fails
const opt = { refetchInterval: POLL, retry: 1, staleTime: 1000 };

export const useSummary = () => useQuery({ queryKey: ["summary"], queryFn: () => api.get<Summary>("/api/dashboard/summary"), ...opt });
export const useStations = () => useQuery({ queryKey: ["stations"], queryFn: async () => {
  const cv = await api.get<{ id: string }[]>("/api/conveyors");
  return api.get<Station[]>(`/api/conveyors/${cv[0].id}/stations`);
}, ...opt });
export const useAnomalies = (q = "status=ACTIVE&limit=100") => useQuery({ queryKey: ["anomalies", q], queryFn: () => api.get<Page<Anomaly>>(`/api/anomalies?${q}`), ...opt });
export const usePredictions = () => useQuery({ queryKey: ["predictions"], queryFn: () => api.get<Page<Prediction>>("/api/predictions?limit=50"), ...opt });
export const useTrend = (st: string) => useQuery({ queryKey: ["trend", st], queryFn: () => api.get<{ points: { t: string; risk: number }[] }>(`/api/predictions/trend/${st}?hours=24`), ...opt });
export const useReadings = (st: string, hours: number) => useQuery({ queryKey: ["readings", st, hours], queryFn: () => api.get<{ points: Point[] }>(`/api/sensors/${st}/readings?hours=${hours}&max_points=240`), ...opt });
export const useDetections = () => useQuery({ queryKey: ["detections"], queryFn: () => api.get<Page<Detection>>("/api/vision/detections?limit=100"), ...opt });
export const useSegments = () => useQuery({ queryKey: ["segments"], queryFn: () => api.get<{ tracker: SimStatus["belt"]; segments: Segment[] }>("/api/vision/segments"), ...opt });
export const useSim = () => useQuery({ queryKey: ["sim"], queryFn: () => api.get<SimStatus>("/api/simulation/status"), ...opt });
export const useScenarios = () => useQuery({ queryKey: ["scenarios"], queryFn: () => api.get<Scenarios>("/api/simulation/scenarios"), staleTime: Infinity });
export const useVisionInfo = () => useQuery({ queryKey: ["vinfo"], queryFn: () => api.get<any>("/api/vision/info"), staleTime: Infinity });
export const useStationHealth = (st: string | null) => useQuery({ queryKey: ["shealth", st], enabled: !!st, queryFn: () => api.get<any>(`/api/stations/${st}/health`), ...opt });
