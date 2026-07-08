"use client";

import type { DependencyGraph } from "./types";

// Deterministic circular layout — no graph library, no physics, same picture
// every time. Design note: docs/architecture/DEPENDENCY_GRAPH.md.
const WIDTH = 620;
const HEIGHT = 480;
const CENTER_X = WIDTH / 2;
const CENTER_Y = 220;
const RADIUS = 170;

function fileName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1];
}

export function DependencyGraphView({ graph }: { graph: DependencyGraph }) {
  const connected = graph.nodes.filter((node) => node.in_degree + node.out_degree > 0);
  const isolated = graph.nodes.length - connected.length;

  if (connected.length === 0) {
    return (
      <p className="text-sm text-zinc-500">No import relationships found in this repository.</p>
    );
  }

  const positions = new Map<string, { x: number; y: number }>();
  connected.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / connected.length - Math.PI / 2;
    positions.set(node.path, {
      x: CENTER_X + RADIUS * Math.cos(angle),
      y: CENTER_Y + RADIUS * Math.sin(angle),
    });
  });

  return (
    <div className="space-y-2">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full rounded-md border border-zinc-800 bg-zinc-950"
        role="img"
        aria-label="Repository dependency graph"
      >
        <defs>
          <marker
            id="dependency-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-zinc-500" />
          </marker>
        </defs>

        {graph.edges.map((edge, index) => {
          const from = positions.get(edge.source);
          const to = positions.get(edge.target);
          if (!from || !to) return null;
          // Stop short of the target node so its arrowhead stays visible.
          const dx = to.x - from.x;
          const dy = to.y - from.y;
          const length = Math.hypot(dx, dy) || 1;
          const endX = to.x - (dx / length) * 16;
          const endY = to.y - (dy / length) * 16;
          return (
            <line
              key={index}
              x1={from.x}
              y1={from.y}
              x2={endX}
              y2={endY}
              className="stroke-zinc-700"
              strokeWidth={1}
              markerEnd="url(#dependency-arrow)"
            />
          );
        })}

        {connected.map((node) => {
          const point = positions.get(node.path);
          if (!point) return null;
          const radius = 5 + Math.min(node.in_degree, 6) * 2.5;
          return (
            <g key={node.path}>
              <title>
                {node.path} — imported by {node.in_degree}, imports {node.out_degree}
              </title>
              <circle
                cx={point.x}
                cy={point.y}
                r={radius}
                className={node.in_degree > 0 ? "fill-emerald-500/80" : "fill-zinc-400"}
              />
              <text
                x={point.x}
                y={point.y + radius + 12}
                textAnchor="middle"
                className="fill-zinc-300 text-[10px]"
              >
                {fileName(node.path)}
              </text>
            </g>
          );
        })}
      </svg>

      <p className="text-xs text-zinc-500">
        {connected.length} connected files · {graph.edges.length} imports
        {isolated > 0 ? ` · ${isolated} unconnected` : ""} · larger dots are imported more
      </p>
    </div>
  );
}
