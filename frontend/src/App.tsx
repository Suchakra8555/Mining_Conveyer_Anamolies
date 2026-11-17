import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Anomalies from "./pages/Anomalies";
import Conveyor from "./pages/Conveyor";
import Overview from "./pages/Overview";
import Predictions from "./pages/Predictions";
import Simulation from "./pages/Simulation";
import Stations from "./pages/Stations";
import Vision from "./pages/Vision";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="conveyor" element={<Conveyor />} />
        <Route path="stations" element={<Stations />} />
        <Route path="anomalies" element={<Anomalies />} />
        <Route path="predictions" element={<Predictions />} />
        <Route path="vision" element={<Vision />} />
        <Route path="simulation" element={<Simulation />} />
      </Route>
    </Routes>
  );
}
