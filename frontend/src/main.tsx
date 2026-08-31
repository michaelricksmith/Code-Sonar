import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App.tsx";
import { ProjectDashboardPanel } from "./components/ProjectDashboardPanel";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <div className="mx-auto max-w-6xl px-6 pt-8">
        <ProjectDashboardPanel />
      </div>
      <App />
    </div>
  </React.StrictMode>,
);
