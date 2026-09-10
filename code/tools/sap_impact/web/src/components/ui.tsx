import type { ReactNode } from "react";
import type { Severity } from "../types";

const SEVERITY_LABEL: Record<Severity, string> = {
  LOW: "낮음", MEDIUM: "보통", HIGH: "높음", CRITICAL: "매우 높음",
};

export function SeverityPill({ severity }: { severity: Severity }) {
  return <span className={`pill ${severity}`}>위험도 {SEVERITY_LABEL[severity] ?? severity}</span>;
}

export function Panel({ title, note, actions, children }: {
  title?: string; note?: string; actions?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <header className="panel-head">
          {title && <h2 className="panel-title">{title}</h2>}
          {note && <span className="panel-note">{note}</span>}
          <span className="spacer" />
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({ label, value, note, warn }: {
  label: string; value: ReactNode; note?: string; warn?: boolean;
}) {
  return (
    <div className={`tile${warn ? " warn" : ""}`}>
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {note && <span className="tile-note">{note}</span>}
    </div>
  );
}

export function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  return (
    <div className="bar-track" aria-hidden="true">
      <div className="bar-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error-box">{message}</div>;
}

export function Notice({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="notice">
      <div className="notice-title">{title}</div>
      <div className="small">{children}</div>
    </div>
  );
}

/** Evidence is the product's core promise: never show a claim without one. */
export function EvidenceLine({ file, line, kind, statement }: {
  file: string; line: number; kind: string; statement: string;
}) {
  return (
    <div className="col" style={{ gap: 3 }}>
      <div className="row small" style={{ gap: 6 }}>
        <span className="code-chip">{file}:{line}</span>
        <span className="muted">{kind}</span>
      </div>
      {statement && <code className="muted">{statement}</code>}
    </div>
  );
}
