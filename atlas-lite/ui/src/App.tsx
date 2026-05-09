import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { BrowseRoute } from "@/routes/BrowseRoute";
import { EntryPointDetailRoute } from "@/routes/EntryPointDetailRoute";
import { HomeRoute } from "@/routes/HomeRoute";
import { ImpactRoute } from "@/routes/ImpactRoute";
import { NotFoundRoute } from "@/routes/NotFoundRoute";

// /graph pulls in Three.js — keep it off the initial bundle.
const GraphRoute = lazy(() =>
  import("@/routes/GraphRoute").then((m) => ({ default: m.GraphRoute })),
);

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomeRoute />} />
        <Route path="browse" element={<BrowseRoute />} />
        <Route path="entry-points/:id" element={<EntryPointDetailRoute />} />
        <Route path="impact" element={<ImpactRoute />} />
        <Route
          path="graph"
          element={
            <Suspense fallback={null}>
              <GraphRoute />
            </Suspense>
          }
        />
        <Route path="*" element={<NotFoundRoute />} />
      </Route>
    </Routes>
  );
}
