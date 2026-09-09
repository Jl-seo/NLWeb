import { useMemo } from "react";
import type { ImpactReport } from "../types";

/**
 * Impact laid out by distance, not as a force-directed hairball.
 *
 * A reviewer's question is "how far does this reach, and through what" -- so
 * hop count becomes the x axis and every edge runs left to right. A general
 * graph view would answer a question nobody asked and be unreadable past thirty
 * nodes.
 */
const COL_W = 208;
const NODE_H = 34;
const GAP_Y = 10;
const PAD = 16;
const MAX_PER_COL = 9;

interface Node {
  key: string; label: string; sub: string; hop: number; x: number; y: number;
  kind: "changed" | "external" | "normal";
}

export function ImpactGraph({ report, onSelect }: {
  report: ImpactReport; onSelect?: (key: string) => void;
}) {
  const { nodes, edges, width, height, overflow } = useMemo(() => {
    const byHop = new Map<number, { key: string; label: string; sub: string; ext: boolean }[]>();
    byHop.set(0, report.changed_objects.map((key) => ({
      key, label: key, sub: "변경", ext: false,
    })));
    for (const hit of report.impacted) {
      const list = byHop.get(hit.hops) ?? [];
      list.push({
        key: hit.object_key,
        label: hit.object_key,
        sub: hit.object_type_label,
        ext: report.external_contracts.includes(hit.object_key),
      });
      byHop.set(hit.hops, list);
    }

    const hops = [...byHop.keys()].sort((a, b) => a - b);
    const overflowCount: Record<number, number> = {};
    const placed: Node[] = [];
    const index = new Map<string, Node>();
    let maxRows = 0;

    hops.forEach((hop, col) => {
      const all = byHop.get(hop) ?? [];
      const shown = all.slice(0, MAX_PER_COL);
      overflowCount[hop] = all.length - shown.length;
      maxRows = Math.max(maxRows, shown.length + (overflowCount[hop] > 0 ? 1 : 0));
      shown.forEach((item, row) => {
        const node: Node = {
          key: item.key, label: item.label, sub: item.sub, hop,
          x: PAD + col * COL_W,
          y: PAD + 24 + row * (NODE_H + GAP_Y),
          kind: hop === 0 ? "changed" : item.ext ? "external" : "normal",
        };
        placed.push(node);
        if (!index.has(item.key)) index.set(item.key, node);
      });
    });

    // One edge per impacted object: the shortest path's last step, which is the
    // reference the evidence panel shows.
    const links: { from: Node; to: Node }[] = [];
    for (const hit of report.impacted) {
      const to = index.get(hit.object_key);
      const parentKey = hit.path[hit.path.length - 2];
      const from = parentKey ? index.get(parentKey) : undefined;
      if (from && to) links.push({ from, to });
    }

    return {
      nodes: placed,
      edges: links,
      width: PAD * 2 + Math.max(1, hops.length) * COL_W,
      height: PAD * 2 + 30 + maxRows * (NODE_H + GAP_Y),
      overflow: overflowCount,
    };
  }, [report]);

  if (!report.impacted.length) return null;
  const hops = [...new Set(nodes.map((n) => n.hop))].sort((a, b) => a - b);

  return (
    <div className="graph-wrap">
      <svg width={width} height={height} role="img"
           aria-label={`영향 경로 그래프: 변경 ${report.changed_objects.length}건에서 ${report.impacted_count}건에 도달`}>
        {hops.map((hop, col) => (
          <text key={`h${hop}`} x={PAD + col * COL_W} y={PAD + 8}
                fill="var(--muted)" fontSize="11" fontFamily="var(--font)">
            {hop === 0 ? "변경 대상" : `${hop}홉`}
          </text>
        ))}
        {edges.map((edge, i) => {
          const x1 = edge.from.x + COL_W - 40;
          const y1 = edge.from.y + NODE_H / 2;
          const x2 = edge.to.x - 4;
          const y2 = edge.to.y + NODE_H / 2;
          const mid = (x1 + x2) / 2;
          return (
            <path key={i} d={`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
                  fill="none" stroke="var(--border-strong)" strokeWidth="1.2" />
          );
        })}
        {nodes.map((node) => {
          const fill = node.kind === "changed" ? "var(--accent-soft)"
            : node.kind === "external" ? "var(--sev-high-bg)" : "var(--surface-2)";
          const stroke = node.kind === "changed" ? "var(--accent)"
            : node.kind === "external" ? "var(--sev-high)" : "var(--border-strong)";
          const label = node.label.length > 24 ? `${node.label.slice(0, 23)}…` : node.label;
          return (
            <g key={node.key} className="graph-node" onClick={() => onSelect?.(node.key)}>
              <title>{`${node.key} — ${node.sub}`}</title>
              <rect x={node.x} y={node.y} width={COL_W - 44} height={NODE_H} rx="6"
                    fill={fill} stroke={stroke} strokeWidth="1" />
              <text x={node.x + 10} y={node.y + 15} fontSize="11.5" fontFamily="var(--mono)"
                    fill="var(--text)">{label}</text>
              <text x={node.x + 10} y={node.y + 27} fontSize="10" fontFamily="var(--font)"
                    fill="var(--muted)">{node.sub}</text>
            </g>
          );
        })}
        {hops.map((hop, col) => {
          const extra = overflow[hop] ?? 0;
          if (!extra) return null;
          const rows = nodes.filter((n) => n.hop === hop).length;
          return (
            <text key={`o${hop}`} x={PAD + col * COL_W + 10}
                  y={PAD + 24 + rows * (NODE_H + GAP_Y) + 16}
                  fontSize="11" fill="var(--muted)" fontFamily="var(--font)">
              + {extra}건 더
            </text>
          );
        })}
      </svg>
    </div>
  );
}
