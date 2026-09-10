import type { Annotation, ReviewFile } from "../types";

const SEVERITY_MARK: Record<Annotation["severity"], string> = {
  high: "위험", medium: "확인", blind: "사각지대", info: "참고",
};

/**
 * A diff that says what each added line does.
 *
 * The annotations come from the same patterns the reference extractor uses, so
 * a line flagged here as a database write is the same line that put an edge in
 * the impact graph. A reviewer never has to reconcile two different readings of
 * the same statement.
 */
export function DiffView({ file }: { file: ReviewFile }) {
  const byLine = new Map<number, Annotation[]>();
  for (const note of file.annotations) {
    byLine.set(note.line, [...(byLine.get(note.line) ?? []), note]);
  }

  if (!file.hunks.length) {
    return <div className="empty">표시할 diff가 없습니다 (바이너리이거나 변경 없음).</div>;
  }

  return (
    <div className="diff">
      {file.hunks.map((hunk, hi) => (
        <div key={hi}>
          <div className="hunk-head">
            @@ -{hunk.old_start} +{hunk.new_start} @@ {hunk.header}
          </div>
          {hunk.lines.map((line, li) => {
            const notes = line.kind === "add" && line.new ? byLine.get(line.new) ?? [] : [];
            return (
              <div key={li}>
                <div className={`diff-row ${line.kind}`}>
                  <span className="diff-no">{line.old ?? ""}</span>
                  <span className="diff-no">{line.new ?? ""}</span>
                  <span className="diff-text">
                    {line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "} {line.text}
                  </span>
                </div>
                {notes.map((note, ni) => (
                  <div key={ni} className={`diff-note note-${note.severity}`}>
                    <span className={`pill ${note.severity === "high" ? "HIGH"
                      : note.severity === "blind" ? "MEDIUM" : "neutral"}`}>
                      {SEVERITY_MARK[note.severity]}
                    </span>
                    <span>{note.label}{note.detail ? ` — ${note.detail}` : ""}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
