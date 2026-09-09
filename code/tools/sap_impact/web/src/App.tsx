import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { AgentPanel } from "./components/AgentPanel";
import { initTeams } from "./teams";
import type { WorkspaceInfo } from "./types";
import { ConfigView } from "./views/Config";
import { DashboardView } from "./views/Dashboard";
import { ExploreView } from "./views/Explore";
import { ImpactView } from "./views/Impact";
import { ReviewView } from "./views/Review";

const NAV = [
  { to: "/", label: "대시보드", end: true },
  { to: "/impact", label: "영향 분석", end: false },
  { to: "/review", label: "코드 리뷰", end: false },
  { to: "/explore", label: "오브젝트 탐색", end: false },
];

const TITLES: Record<string, string> = {
  "/": "대시보드",
  "/impact": "영향 분석",
  "/review": "코드 리뷰",
  "/explore": "오브젝트 탐색",
};

export default function App() {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [workspace, setWorkspace] = useState<string | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [agentSeed, setAgentSeed] = useState<string | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const setTheme = (theme: "light" | "dark") =>
      document.documentElement.setAttribute("data-theme", theme);
    void initTeams(setTheme).then((ctx) => setTheme(ctx.theme));
  }, []);

  const loadWorkspaces = useCallback(async () => {
    try {
      const list = await api.workspaces();
      setWorkspaces(list);
      setWorkspace((current) => current ?? list[0]?.id ?? null);
    } catch {
      setWorkspaces([]);
    }
  }, []);

  useEffect(() => { void loadWorkspaces(); }, [loadWorkspaces]);

  const current = useMemo(
    () => workspaces.find((w) => w.id === workspace),
    [workspaces, workspace],
  );

  const askAgent = useCallback((question: string) => {
    setAgentSeed(question);
    setAgentOpen(true);
  }, []);

  async function reindex() {
    if (!workspace) return;
    setReindexing(true);
    try {
      await api.reindex(workspace);
      setTimeout(() => { void loadWorkspaces(); setReindexing(false); }, 2500);
    } catch {
      setReindexing(false);
    }
  }

  return (
    <div className="shell">
      <nav className="rail">
        <div className="brand">
          <span className="brand-mark">SI</span>
          <span className="col" style={{ gap: 0 }}>
            <span className="brand-name">변경 영향 분석</span>
            <span className="brand-sub">SAP ABAP · BTP</span>
          </span>
        </div>
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}
                   className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
            {item.label}
          </NavLink>
        ))}
        <div className="rail-foot">
          {current?.indexed_at ? `인덱스 ${current.indexed_at}` : "인덱스 정보 없음"}
        </div>
      </nav>

      <div className="main">
        <header className="topbar">
          <span className="topbar-title">{TITLES[location.pathname] ?? "변경 영향 분석"}</span>
          <span className="spacer" />
          {workspaces.length > 1 && (
            <select id="workspace-select" value={workspace ?? ""}
                    onChange={(e) => setWorkspace(e.target.value)}>
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>{w.id}{w.ready ? "" : " (인덱싱 중)"}</option>
              ))}
            </select>
          )}
          {current && (
            <span className="small muted">
              오브젝트 {current.objects.toLocaleString()} · 참조 {current.references.toLocaleString()}
            </span>
          )}
          <button className="btn sm" disabled={reindexing || !workspace} onClick={() => void reindex()}>
            {reindexing ? "재인덱싱 중…" : "재인덱싱"}
          </button>
          <button className="btn primary sm" onClick={() => { setAgentSeed(null); setAgentOpen(true); }}>
            에이전트
          </button>
        </header>

        <main className="content">
          <div className="content-inner">
            <Routes>
              <Route path="/" element={<DashboardView workspace={workspace} onAskAgent={askAgent} />} />
              <Route path="/impact" element={<ImpactView workspace={workspace} onAskAgent={askAgent} />} />
              <Route path="/review" element={<ReviewView workspace={workspace} onAskAgent={askAgent} />} />
              <Route path="/explore" element={<ExploreView workspace={workspace} />} />
              <Route path="/config" element={<ConfigView />} />
            </Routes>
          </div>
        </main>
      </div>

      {agentOpen && (
        <AgentPanel
          context={{ workspace, screen: location.pathname, query: location.search }}
          seed={agentSeed}
          onClose={() => { setAgentOpen(false); setAgentSeed(null); }}
        />
      )}
    </div>
  );
}
