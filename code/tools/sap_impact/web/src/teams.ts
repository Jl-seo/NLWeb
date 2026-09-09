import { app as teamsApp } from "@microsoft/teams-js";

/**
 * Teams integration is optional by design: the same build runs as a Teams tab,
 * as a standalone web app, and in a browser during development. Anything Teams
 * gives us (theme, deep-link context) is treated as an enhancement.
 */
export interface TeamsContext {
  inTeams: boolean;
  theme: "light" | "dark";
  subPage?: string;
}

export async function initTeams(onTheme: (theme: "light" | "dark") => void): Promise<TeamsContext> {
  try {
    await teamsApp.initialize();
    const ctx = await teamsApp.getContext();
    const theme = ctx.app.theme === "default" ? "light" : "dark";
    teamsApp.registerOnThemeChangeHandler((t) => onTheme(t === "default" ? "light" : "dark"));
    return { inTeams: true, theme, subPage: ctx.page?.subPageId };
  } catch {
    const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)");
    prefersDark?.addEventListener?.("change", (e) => onTheme(e.matches ? "dark" : "light"));
    return { inTeams: false, theme: prefersDark?.matches ? "dark" : "light" };
  }
}
