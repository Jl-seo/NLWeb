import { useEffect, useState } from "react";
import { pages } from "@microsoft/teams-js";
import { api } from "../api";
import { Panel } from "../components/ui";
import type { WorkspaceInfo } from "../types";

/**
 * Teams channel-tab configuration. Only reachable from the Teams tab-add flow;
 * opening it in a browser simply shows the picker with the save disabled.
 */
export function ConfigView() {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [inTeams, setInTeams] = useState(false);

  useEffect(() => {
    void api.workspaces().then((list) => {
      setWorkspaces(list);
      setSelected(list[0]?.id ?? "");
    }).catch(() => setWorkspaces([]));
  }, []);

  useEffect(() => {
    try {
      pages.config.registerOnSaveHandler((event) => {
        void pages.config.setConfig({
          entityId: "sapImpact",
          contentUrl: `${location.origin}/app/?workspace=${encodeURIComponent(selected)}`,
          suggestedDisplayName: "SAP 영향 분석",
        }).then(() => event.notifySuccess());
      });
      pages.config.setValidityState(true);
      setInTeams(true);
    } catch {
      setInTeams(false);
    }
  }, [selected]);

  return (
    <Panel title="탭 설정" note="이 채널에서 기본으로 사용할 코드베이스를 선택하세요">
      <select id="config-workspace" value={selected} onChange={(e) => setSelected(e.target.value)}>
        {workspaces.map((w) => <option key={w.id} value={w.id}>{w.id}</option>)}
        {workspaces.length === 0 && <option value="">(등록된 코드베이스 없음)</option>}
      </select>
      {!inTeams && (
        <span className="small muted">
          Teams 밖에서 열린 화면입니다. 저장은 Teams의 탭 추가 화면에서만 동작합니다.
        </span>
      )}
    </Panel>
  );
}
