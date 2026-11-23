/** Versão do painel web (package.json), injetada pelo Vite (vite.config.ts: define). */
declare const __APP_VERSION__: string;

export const PANEL_VERSION = __APP_VERSION__;
/** Ex.: "v0.2.0" */
export const versionLabel = `v${PANEL_VERSION}`;
