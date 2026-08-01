// Chart.js vem só via CDN (UMD global, não instalado via npm) — tipagem
// mínima ambiente em vez de @types/chart.js, para não puxar uma dependência
// npm que não é usada em runtime (a build não faz bundling do Chart.js).
declare const Chart: any;

// SheetJS (xlsx) idem — CDN, usado só para exportar os resultados do
// agrupamento (K-Means/DBSCAN) em .xlsx (ver exportClusterToExcel em app.ts).
declare const XLSX: any;

// Não está em lib.dom.d.ts (evento não padronizado, só Chromium/Edge).
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

// VLibras (script CDN carregado em index.html) — só o que é usado aqui.
interface Window {
  VLibras?: {
    Widget: new (url: string) => unknown;
  };
}
