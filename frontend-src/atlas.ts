// Atlas Nacional de Paisagem — Fase 0 (Diversidade). Página pública,
// independente do app autenticado (compilada separadamente para
// static/atlas.js — ver tsconfig.atlas.json). Consome só rotas públicas
// (/api/atlas/*, /api/ibge/ufs) — nunca envia Authorization.

function $<T extends HTMLElement = HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

interface MetricaOption {
  key: string;
  label: string;
  formato: (v: number) => string;
}

const METRICAS: MetricaOption[] = [
  { key: "shannon_diversity_index", label: "Diversidade da paisagem (SHDI)", formato: (v) => v.toFixed(2) },
  { key: "patch_richness", label: "Riqueza de classes", formato: (v) => String(Math.round(v)) },
  { key: "area_natural_pct", label: "% de área natural", formato: (v) => `${v.toFixed(1)}%` },
  { key: "area_antropizada_pct", label: "% de área antropizada", formato: (v) => `${v.toFixed(1)}%` },
  { key: "classe_dominante_pct", label: "% da classe dominante", formato: (v) => `${v.toFixed(1)}%` },
];

function metricaInfo(key: string): MetricaOption {
  return METRICAS.find((m) => m.key === key) || METRICAS[0];
}

const state: { ano: number | null; metrica: string; uf: string } = {
  ano: null,
  metrica: METRICAS[0].key,
  uf: "",
};

let map: L.Map;
let geojsonLayer: L.GeoJSON | null = null;
let municipioChart: any = null;

async function fetchJson(url: string): Promise<any> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`${url} -> HTTP ${resp.status}`);
  }
  return resp.json();
}

// Escala de cor sequencial simples (5 faixas por quantil) — sem dependência
// externa, seguindo o mesmo espírito de app.ts (nenhuma lib de escala de
// cor é usada em nenhum outro lugar do projeto).
const CORES_ESCALA = ["#fde68a", "#a7f3d0", "#6ee7b7", "#10b981", "#065f46"];

function corPorQuantil(valor: number, valores: number[]): string {
  if (valores.length === 0) return CORES_ESCALA[0];
  const ordenados = [...valores].sort((a, b) => a - b);
  const posicao = ordenados.filter((v) => v <= valor).length / ordenados.length;
  const indice = Math.min(CORES_ESCALA.length - 1, Math.floor(posicao * CORES_ESCALA.length));
  return CORES_ESCALA[indice];
}

async function popularAnos(): Promise<void> {
  const data = await fetchJson("/api/atlas/anos-disponiveis");
  const anos: number[] = data.anos || [];
  const select = $<HTMLSelectElement>("atlas-ano");
  select.innerHTML = anos.map((a) => `<option value="${a}">${a}</option>`).join("");
  if (anos.length > 0) {
    state.ano = anos[anos.length - 1];
    select.value = String(state.ano);
  }
}

async function popularUfs(): Promise<void> {
  try {
    const ufs: { sigla: string; nome: string }[] = await fetchJson("/api/ibge/ufs");
    const select = $<HTMLSelectElement>("atlas-uf");
    select.innerHTML =
      `<option value="">Brasil (todas as UFs)</option>` +
      ufs.map((uf) => `<option value="${uf.sigla}">${uf.nome}</option>`).join("");
  } catch (err) {
    console.warn("Não foi possível carregar a lista de UFs:", err);
  }
}

function popularMetricas(): void {
  const select = $<HTMLSelectElement>("atlas-metrica");
  select.innerHTML = METRICAS.map((m) => `<option value="${m.key}">${m.label}</option>`).join("");
  select.value = state.metrica;
}

function initMap(): void {
  map = L.map("atlas-map").setView([-15.78, -47.93], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
  }).addTo(map);
}

async function carregarMapa(): Promise<void> {
  if (state.ano === null) return;
  const params = new URLSearchParams({ ano: String(state.ano), metrica: state.metrica });
  if (state.uf) params.set("uf", state.uf);

  const geojson = await fetchJson(`/api/atlas/mapa?${params.toString()}`);
  const valores: number[] = (geojson.features || [])
    .map((f: any) => f.properties.valor)
    .filter((v: number) => v !== null && v !== undefined);

  if (geojsonLayer) {
    map.removeLayer(geojsonLayer);
  }

  geojsonLayer = L.geoJSON(geojson, {
    style: (feature: any) => ({
      fillColor: corPorQuantil(feature.properties.valor, valores),
      fillOpacity: 0.75,
      color: "#0f172a",
      weight: 0.5,
    }),
    onEachFeature: (feature: any, layer: L.Layer) => {
      const info = metricaInfo(state.metrica);
      const valor = feature.properties.valor;
      layer.bindTooltip(
        `<strong>${feature.properties.nome}/${feature.properties.uf}</strong><br>${info.label}: ${
          valor !== null && valor !== undefined ? info.formato(valor) : "sem dado"
        }`
      );
      layer.on("click", () =>
        carregarPerfilMunicipio(feature.properties.codigo_ibge, `${feature.properties.nome}/${feature.properties.uf}`)
      );
    },
  }).addTo(map);

  if (geojson.features && geojson.features.length > 0) {
    map.fitBounds(geojsonLayer.getBounds(), { maxZoom: state.uf ? 7 : 4 });
  }
}

async function carregarRanking(): Promise<void> {
  if (state.ano === null) return;
  const params = new URLSearchParams({
    ano: String(state.ano), metrica: state.metrica, ordem: "desc", limit: "20",
  });
  if (state.uf) params.set("uf", state.uf);

  const data = await fetchJson(`/api/atlas/ranking?${params.toString()}`);
  const info = metricaInfo(state.metrica);
  const tbody = $<HTMLTableSectionElement>("atlas-ranking-body");
  tbody.innerHTML = (data.municipios || [])
    .map(
      (m: any, i: number) => `
      <tr data-codigo="${m.municipio_codigo}" data-nome="${m.municipio_nome}/${m.municipio_uf}" class="atlas-ranking-row">
        <td>${i + 1}</td>
        <td>${m.municipio_nome}/${m.municipio_uf}</td>
        <td>${info.formato(m.valor)}</td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll<HTMLTableRowElement>(".atlas-ranking-row").forEach((row) => {
    row.addEventListener("click", () => carregarPerfilMunicipio(row.dataset.codigo!, row.dataset.nome));
  });
}

async function carregarRankingTendencia(): Promise<void> {
  const anosResp = await fetchJson("/api/atlas/anos-disponiveis");
  const anos: number[] = anosResp.anos || [];
  if (anos.length < 2) return;

  const params = new URLSearchParams({
    ano_inicio: String(anos[0]), ano_fim: String(anos[anos.length - 1]), limit: "10",
  });
  if (state.uf) params.set("uf", state.uf);

  const data = await fetchJson(`/api/atlas/ranking-tendencia?${params.toString()}`);
  $("atlas-tendencia-titulo").textContent =
    `Maior perda de vegetação natural (${anos[0]} → ${anos[anos.length - 1]})`;

  const tbody = $<HTMLTableSectionElement>("atlas-tendencia-body");
  tbody.innerHTML = (data.municipios || [])
    .map(
      (m: any, i: number) => `
      <tr data-codigo="${m.municipio_codigo}" data-nome="${m.municipio_nome}/${m.municipio_uf}" class="atlas-ranking-row">
        <td>${i + 1}</td>
        <td>${m.municipio_nome}/${m.municipio_uf}</td>
        <td class="${m.variacao_area_natural_pp < 0 ? "atlas-negativo" : "atlas-positivo"}">
          ${m.variacao_area_natural_pp >= 0 ? "+" : ""}${m.variacao_area_natural_pp.toFixed(1)} p.p.
        </td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll<HTMLTableRowElement>(".atlas-ranking-row").forEach((row) => {
    row.addEventListener("click", () => carregarPerfilMunicipio(row.dataset.codigo!, row.dataset.nome));
  });
}

async function carregarPerfilMunicipio(codigo: string, nomeExibicao?: string): Promise<void> {
  const painel = $("atlas-perfil");
  painel.classList.remove("atlas-hidden");
  painel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("atlas-perfil-titulo").textContent = nomeExibicao || `Município ${codigo}`;

  try {
    const data = await fetchJson(`/api/atlas/municipio/${codigo}`);
    const serie: any[] = data.serie || [];
    const primeiro = serie[0];
    const ultimo = serie[serie.length - 1];
    if (data.tendencia) {
      const variacao = data.tendencia.variacao_area_natural_pp;
      $("atlas-perfil-tendencia").innerHTML =
        `Entre ${data.tendencia.ano_inicio} e ${data.tendencia.ano_fim}, a área natural ` +
        `${variacao < 0 ? "caiu" : "subiu"} <strong>${Math.abs(variacao).toFixed(1)} pontos percentuais</strong> ` +
        `(${primeiro.area_natural_pct.toFixed(1)}% → ${ultimo.area_natural_pct.toFixed(1)}%).`;
    } else {
      $("atlas-perfil-tendencia").textContent = "Só há um ano carregado para este município ainda.";
    }

    const ctx = ($("atlas-perfil-chart") as HTMLCanvasElement).getContext("2d");
    if (municipioChart) municipioChart.destroy();
    municipioChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: serie.map((row) => row.ano),
        datasets: [
          {
            label: "% de área natural",
            data: serie.map((row) => row.area_natural_pct),
            borderColor: "#10b981",
            backgroundColor: "rgba(16, 185, 129, 0.15)",
            fill: true,
            tension: 0.2,
          },
          {
            label: "% de área antropizada",
            data: serie.map((row) => row.area_antropizada_pct),
            borderColor: "#f59e0b",
            fill: false,
            tension: 0.2,
          },
        ],
      },
      options: { responsive: true, scales: { y: { beginAtZero: true, max: 100 } } },
    });
  } catch (err) {
    $("atlas-perfil-tendencia").textContent =
      "Nenhum dado do Atlas para este município ainda (só municípios já processados por scripts/build_diversity_atlas.py aparecem aqui).";
  }
}

function wireFiltros(): void {
  $<HTMLSelectElement>("atlas-ano").addEventListener("change", (e) => {
    state.ano = Number((e.target as HTMLSelectElement).value);
    carregarMapa();
    carregarRanking();
  });
  $<HTMLSelectElement>("atlas-metrica").addEventListener("change", (e) => {
    state.metrica = (e.target as HTMLSelectElement).value;
    carregarMapa();
    carregarRanking();
  });
  $<HTMLSelectElement>("atlas-uf").addEventListener("change", (e) => {
    state.uf = (e.target as HTMLSelectElement).value;
    carregarMapa();
    carregarRanking();
    carregarRankingTendencia();
  });
}

async function init(): Promise<void> {
  initMap();
  popularMetricas();
  wireFiltros();
  await Promise.all([popularAnos(), popularUfs()]);
  await Promise.all([carregarMapa(), carregarRanking(), carregarRankingTendencia()]);
}

document.addEventListener("DOMContentLoaded", () => {
  init().catch((err) => {
    console.error("Falha ao carregar o Atlas Nacional de Paisagem:", err);
    $("atlas-erro").classList.remove("atlas-hidden");
  });
});
