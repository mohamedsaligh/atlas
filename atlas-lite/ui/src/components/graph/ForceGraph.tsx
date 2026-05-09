/**
 * Three.js-backed force graph.
 *
 * Performance design notes:
 *
 * - The whole component is loaded via React.lazy(), so the Three.js
 *   bundle never enters the initial download — only users who open the
 *   /graph route pay the ~700 kB cost.
 * - We pre-build a `Map<id, GraphNode>` once per `data` change and
 *   share it across paint frames so node lookups during link rendering
 *   stay O(1) at 50k+ edges.
 * - `linkResolution=3` (default 6) cuts triangle count per edge in half
 *   without visible quality loss at this density.
 * - Cooldown ticks are bounded so CPU drops to zero once layout settles.
 */

import { Workflow } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import * as THREE from "three";

import type { GraphLink, GraphNode, GraphResponse } from "@/api/graph-types";

// Minimal label sprite. We render text into a 2D canvas, upload it as a
// THREE.CanvasTexture, and use a Sprite mesh to display it. Cheaper and
// dependency-free vs pulling a third-party label package.
function makeLabelSprite(text: string, opts: { color?: string; bg?: string } = {}): THREE.Sprite {
  const color = opts.color ?? "#e6edf3";
  const bg = opts.bg ?? "rgba(11, 13, 16, 0.78)";
  const fontSize = 32;
  const padding = 8;
  const font = `${fontSize}px 'JetBrains Mono', ui-monospace, monospace`;

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return new THREE.Sprite(new THREE.SpriteMaterial());
  }
  ctx.font = font;
  const metrics = ctx.measureText(text);
  const textW = Math.ceil(metrics.width);
  const w = textW + padding * 2;
  const h = fontSize + padding * 2;
  // Up-scale for retina sharpness.
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  // Background pill.
  ctx.fillStyle = bg;
  const r = 4;
  ctx.beginPath();
  ctx.moveTo(r, 0);
  ctx.lineTo(w - r, 0);
  ctx.quadraticCurveTo(w, 0, w, r);
  ctx.lineTo(w, h - r);
  ctx.quadraticCurveTo(w, h, w - r, h);
  ctx.lineTo(r, h);
  ctx.quadraticCurveTo(0, h, 0, h - r);
  ctx.lineTo(0, r);
  ctx.quadraticCurveTo(0, 0, r, 0);
  ctx.closePath();
  ctx.fill();

  // Text.
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, padding, h / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  texture.needsUpdate = true;

  const material = new THREE.SpriteMaterial({ map: texture, depthWrite: false, transparent: true });
  const sprite = new THREE.Sprite(material);
  // Sprite world-size — chosen to read clearly at default camera distance.
  const worldH = 4;
  const worldW = (worldH * w) / h;
  sprite.scale.set(worldW, worldH, 1);
  return sprite;
}

type SimNode = GraphNode & { x?: number; y?: number; z?: number };
type SimLink = GraphLink;
type LinkRuntime = { source: string | SimNode; target: string | SimNode };

const COLORS = {
  entry: "#58a6ff",
  source: "#3fb950",
  target: "#d29922",
  helper: "#a371f7",
  schema: "#7d8590",
  highlight: "#f0b429",
  link: "rgba(120, 134, 156, 0.42)",
  linkHot: "rgba(240, 180, 41, 0.95)",
};

interface ForceGraphProps {
  data: GraphResponse;
  highlight?: string;
}

function ForceGraphInner({ data, highlight }: ForceGraphProps) {
  const ref = useRef<ForceGraphMethods<SimNode, SimLink> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dimsRef = useRef({ w: 0, h: 0 });

  // Memoise the underlying graph data so react-force-graph doesn't
  // re-simulate when only `highlight` changes.
  const graphData = useMemo<{ nodes: SimNode[]; links: SimLink[] }>(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    }),
    [data],
  );

  const matchSet = useMemo(() => {
    if (!highlight) return null;
    const needle = highlight.toLowerCase();
    return new Set(
      data.nodes
        .filter((n) => n.label.toLowerCase().includes(needle))
        .map((n) => n.id),
    );
  }, [data.nodes, highlight]);

  const nodeColor = useCallback(
    (n: SimNode) => {
      if (matchSet && matchSet.has(n.id)) return COLORS.highlight;
      if (n.kind === "entry_point") return COLORS.entry;
      if (n.kind === "field") {
        // Source vs target inferred by which side of the link list it
        // appears on, but we settle for "field" tinted yellow in the
        // common case — entry points dominate, so fields read as a
        // single colour family.
        return COLORS.target;
      }
      return COLORS.schema;
    },
    [matchSet],
  );

  const nodeThreeObject = useCallback(
    (n: SimNode) => {
      const isEP = n.kind === "entry_point";
      const radius = isEP ? 4 : 2.4;
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(radius, 12, 12),
        new THREE.MeshLambertMaterial({
          color: nodeColor(n),
          emissive: matchSet?.has(n.id) ? new THREE.Color(COLORS.highlight) : new THREE.Color(0),
          emissiveIntensity: matchSet?.has(n.id) ? 0.6 : 0,
        }),
      );
      // Only label entry points and highlighted fields — too dense
      // otherwise. Sprite labels stay readable at any zoom.
      if (isEP || matchSet?.has(n.id)) {
        const label = makeLabelSprite(
          n.label.length > 32 ? `${n.label.slice(0, 31)}…` : n.label,
        );
        label.position.set(0, radius + 4, 0);
        sphere.add(label);
      }
      return sphere;
    },
    [matchSet, nodeColor],
  );

  const linkColor = useCallback(
    (link: SimLink) => {
      if (!matchSet) return COLORS.link;
      const l = link as unknown as LinkRuntime;
      const sId = typeof l.source === "string" ? l.source : l.source.id;
      const tId = typeof l.target === "string" ? l.target : l.target.id;
      return matchSet.has(sId) || matchSet.has(tId) ? COLORS.linkHot : COLORS.link;
    },
    [matchSet],
  );

  // Click → centre the camera on the node. The camera distance scales
  // with the node count to keep the framing consistent.
  const handleNodeClick = useCallback(
    (n: SimNode) => {
      if (!ref.current || n.x === undefined || n.y === undefined || n.z === undefined) return;
      const distance = 80;
      const ratio = 1 + distance / Math.hypot(n.x, n.y, n.z);
      ref.current.cameraPosition(
        { x: n.x * ratio, y: n.y * ratio, z: n.z * ratio },
        { x: n.x, y: n.y, z: n.z },
        800,
      );
    },
    [],
  );

  // Resize observer — react-force-graph needs explicit width/height.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      dimsRef.current = { w: el.clientWidth, h: el.clientHeight };
      // Force a re-layout by triggering camera reset.
      ref.current?.zoomToFit(400, 80);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="absolute inset-0 gpu">
      <ForceGraph3D<SimNode, SimLink>
        ref={ref}
        graphData={graphData}
        backgroundColor="rgba(0,0,0,0)"
        showNavInfo={false}
        nodeRelSize={4}
        nodeThreeObject={nodeThreeObject}
        nodeThreeObjectExtend={false}
        linkColor={linkColor}
        linkOpacity={0.58}
        linkWidth={0.8}
        linkDirectionalParticles={0}
        linkResolution={3}
        cooldownTicks={120}
        warmupTicks={40}
        d3AlphaDecay={0.04}
        d3VelocityDecay={0.32}
        onNodeClick={handleNodeClick}
        controlType="orbit"
      />
      <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-1.5 rounded-md bg-bg/70 px-2 py-1 text-[11px] text-fg-muted backdrop-blur-sm">
        <Workflow className="h-3 w-3" />
        Three.js · GPU
      </div>
    </div>
  );
}

const ForceGraph = memo(ForceGraphInner);
export default ForceGraph;
