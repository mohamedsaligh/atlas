import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { BrowseRoute } from "@/routes/BrowseRoute";
import { EntryPointDetailRoute } from "@/routes/EntryPointDetailRoute";
import { HomeRoute } from "@/routes/HomeRoute";
import { NotFoundRoute } from "@/routes/NotFoundRoute";
import { StubRoute } from "@/routes/StubRoute";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomeRoute />} />
        <Route path="browse" element={<BrowseRoute />} />
        <Route path="entry-points/:id" element={<EntryPointDetailRoute />} />
        <Route
          path="impact"
          element={
            <StubRoute
              title="Impact analysis"
              body="Type a schema:path on the right, see every affected target field grouped by scope. Lights up in the next commit."
            />
          }
        />
        <Route
          path="graph"
          element={
            <StubRoute
              title="Force-directed lineage graph"
              body="Obsidian-style 3D graph backed by Three.js. Lights up in the next commit."
            />
          }
        />
        <Route path="*" element={<NotFoundRoute />} />
      </Route>
    </Routes>
  );
}
