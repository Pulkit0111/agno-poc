"use client";

import { useState } from "react";
import { toneClass, verdictMeta } from "@/lib/status";

const VERDICT_ORDER = ["approve", "comment", "request_changes"];

export function ReviewTrendsChart({ byWeek }: { byWeek: Record<string, Record<string, number>> }) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; week: string; counts: Record<string, number> } | null>(null);
  const weeks = Object.keys(byWeek).sort();
  if (!weeks.length) {
    return <div className="px-4 py-8 text-center text-sm text-muted-foreground">No review data yet.</div>;
  }
  const max = Math.max(1, ...weeks.map((w) => Object.values(byWeek[w]).reduce((a, b) => a + b, 0)));
  const W = 760, H = 180, padL = 26, padB = 22, padT = 8;
  const plotH = H - padB - padT;
  const colW = (W - padL) / weeks.length;

  return (
    <div className="relative">
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Stacked weekly bar chart of PR review verdicts">
        {[0, 0.5, 1].map((frac) => {
          const y = padT + plotH - frac * plotH;
          return (
            <line key={frac} x1={padL} x2={W} y1={y} y2={y} stroke="var(--border, #e1e0d9)" strokeWidth={1} />
          );
        })}
        {weeks.map((week, i) => {
          const counts = byWeek[week];
          const x = padL + i * colW + colW * 0.28;
          const bw = colW * 0.44;
          let y = padT + plotH;
          const present = VERDICT_ORDER.filter((v) => counts[v]);
          const extraKeys = Object.keys(counts).filter((k) => !VERDICT_ORDER.includes(k));
          const order = [...present, ...extraKeys];
          return (
            <g key={week}>
              {order.map((verdict, vi) => {
                const v = counts[verdict];
                if (!v) return null;
                let h = (v / max) * plotH - 2;
                if (h < 2) h = 2;
                y -= (v / max) * plotH;
                const isTop = vi === order.length - 1;
                return (
                  <rect
                    key={verdict}
                    x={x} y={y + 1} width={bw} height={h}
                    className={toneClass[verdictMeta(verdict).tone]}
                    fill="currentColor"
                    rx={isTop ? 4 : 0}
                  />
                );
              })}
              <rect
                x={padL + i * colW} y={padT} width={colW} height={plotH} fill="transparent"
                onMouseMove={(e) => {
                  const rect = e.currentTarget.ownerSVGElement!.getBoundingClientRect();
                  setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, week, counts });
                }}
                onMouseLeave={() => setTooltip(null)}
              />
              <text x={padL + i * colW + colW / 2} y={H - 6} textAnchor="middle" fontSize={10} fill="var(--muted-foreground, #898781)">
                {week.slice(-2)}
              </text>
            </g>
          );
        })}
      </svg>
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow-lg"
          style={{ left: tooltip.x + 12, top: tooltip.y - 40 }}
        >
          <div className="font-medium">{tooltip.week}</div>
          {Object.entries(tooltip.counts).map(([k, v]) => (
            <div key={k}>{k}: {v}</div>
          ))}
        </div>
      )}
    </div>
  );
}
