/* ==========================================================================
   Landscape Metrics Extractor - Frontend App Engine (TypeScript)
   Fonte em frontend-src/, compila para static/app.js (ver tsconfig.json).
   Funções ficam no escopo global (module: "none") porque index.html/
   landing.html chamam vários handlers inline via onclick=/onchange=/
   onsubmit=/oninput= — não há <script type="module"> nem bundler aqui.
   ========================================================================== */

// Helper tipado para document.getElementById — assume que o elemento existe
// (mesma premissa do app.js original), só evita repetir casts em toda parte.
function $<T extends HTMLElement = HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

interface LatLngLike {
  lat: number;
  lng: number;
}

let map: L.Map;
let marker: L.Marker | undefined;
let circleBuffer: L.Circle | undefined;
let selectedPoint: LatLngLike | null = null;
let currentTab = 'tab-analise';
let pcaChartInstance: any = null;
let metricsChartInstance: any = null;

// Estado do Tour do Avatar
type AvatarKey = 'maria_julia' | 'pedro';
interface TourStep {
  title: string;
  text: string;
}
let selectedAvatar: AvatarKey = 'maria_julia';
let currentTourStep = 0;
const tourSteps: Record<AvatarKey, TourStep[]> = {
  maria_julia: [
    { title: "Boas-vindas da Maria Júlia! 🌿", text: "Olá! Sou a Maria Júlia, sua especialista em Ciências Ambientais. Vou te orientar no cálculo e interpretação das métricas de paisagem do MapBiomas!" },
    { title: "Área de Interesse 🗺️", text: "Na primeira seção, escolha um ponto de interesse com raio de buffer ou selecione os limites oficiais de um município do IBGE." },
    { title: "Cálculo de Métricas 📊", text: "Clique no botão 'Calcular Métricas' para obter dados de área, número de manchas (NP), densidade de bordas (ED) e diversidade de Shannon (SHDI)." },
    { title: "Agrupamento SSE & Clustering 🤖", text: "Na aba 'Matriz Socioecológica', você pode agrupar municípios por perfil usando os algoritmos K-Means e DBSCAN!" }
  ],
  pedro: [
    { title: "Boas-vindas do Pedro! 🛰️", text: "E aí! Sou o Pedro, engenheiro de dados geoespaciais. Vou te mostrar como processar rasters GeoTIFF e modelos de Machine Learning!" },
    { title: "GeoTIFF & MapBiomas 🛰️", text: "Você pode usar dados diretos do MapBiomas via Earth Engine ou fazer upload dos seus próprios arquivos GeoTIFF de qualquer resolução." },
    { title: "Agrupamento K-Means & DBSCAN 🤖", text: "Execute agrupamentos não supervisionados, analise o Método do Cotovelo (Elbow) e visualize a projeção 2D via PCA dos clusters!" },
    { title: "Estarei no Canto da Tela 📌", text: "Ficarei flutuando aqui no canto da tela. Sempre que precisar de uma dica técnica, basta me dar um toque!" }
  ]
};

// Registro de PWA Service Worker e Prompt de Instalação
let deferredPrompt: BeforeInstallPromptEvent | null = null;
window.addEventListener('beforeinstallprompt', (e: Event) => {
  e.preventDefault();
  deferredPrompt = e as BeforeInstallPromptEvent;
  $('pwa-banner').style.display = 'flex';
});

document.getElementById('pwa-install-btn')?.addEventListener('click', async () => {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      $('pwa-banner').style.display = 'none';
    }
    deferredPrompt = null;
  }
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW Reg error:', err));
}

// Inicialização ao carregar a página
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  loadUfs();
  setupAccessibility();
  checkAuthSession();
  loadGoogleLoginOption();
  toggleTifUpload();
  updateStepper();
});

let authMode: 'login' | 'register' = 'login';

// Access token só em memória (nunca localStorage) — reduz a janela de
// exfiltração via XSS: some ao fechar a aba/recarregar a página, e é
// recuperado no carregamento seguinte via o refresh token (cookie
// httpOnly, não acessível a JS) em _tryRefreshAccessToken. `user_email`
// continua em localStorage só como conveniência de exibição — não é um
// credencial por si só.
let accessToken: string | null = null;

function authHeaders(): Record<string, string> {
  return { 'Authorization': `Bearer ${accessToken}` };
}

// Depois do redirect de /api/auth/google/callback, o access token chega no
// fragmento da URL (#access_token=...&email=...) em vez de um fetch — ver
// docstring de google_callback em backend/app/api/routes/auth.py.
function _consumeGoogleRedirectFragment(): void {
  if (!window.location.hash.includes('access_token=')) return;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get('access_token');
  const email = params.get('email');
  if (token && email) {
    accessToken = token;
    localStorage.setItem('user_email', email);
  }
  window.history.replaceState({}, document.title, window.location.pathname);
}

// Confirma que o access token em memória ainda é aceito pela API — sem
// isso, um token expirado (15min, ver access_token_expire_minutes) deixava
// a UI achando que a sessão seguia válida, mostrando a ferramenta com uma
// sessão na prática já morta.
async function _isAccessTokenValid(token: string): Promise<boolean> {
  try {
    const res = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } });
    return res.ok;
  } catch {
    return false;
  }
}

// Usa o refresh token (cookie httpOnly) para renovar o access token sem
// precisar logar de novo — é assim que a sessão sobrevive a F5 mesmo com o
// access token só em memória (ROADMAP.md, "sessão não sobrevive a F5").
async function _tryRefreshAccessToken(): Promise<string | null> {
  try {
    const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' });
    if (!res.ok) return null;
    const data = await res.json();
    accessToken = data.access_token;
    return accessToken;
  } catch {
    return null;
  }
}

async function checkAuthSession(): Promise<void> {
  _consumeGoogleRedirectFragment();

  const container = $('user-session-container');
  const appShell = $('app-shell');
  let userEmail: string | null = localStorage.getItem('user_email');

  if (!accessToken || !(await _isAccessTokenValid(accessToken))) {
    accessToken = await _tryRefreshAccessToken();
  }
  if (!accessToken) userEmail = null;

  if (accessToken && userEmail) {
    container.innerHTML = `
      <span style="font-size: 0.85rem; color: var(--accent-emerald); font-weight: 600;">👤 ${userEmail}</span>
      <button onclick="logout()" class="btn-outline" style="margin-left: 0.5rem; padding: 0.3rem 0.6rem; font-size: 0.8rem;">Sair</button>
    `;
    closeAuthModal();
    appShell.style.display = 'flex';
    loadGeeCredentialsStatus();
    updateStepper();
  } else {
    accessToken = null;
    localStorage.removeItem('user_email');
    container.innerHTML = `<button id="btn-open-login" class="btn-primary" onclick="openAuthModal()">Entrar / Cadastrar</button>`;
    appShell.style.display = 'none';
    openAuthModal();
  }
}

async function loadGoogleLoginOption(): Promise<void> {
  try {
    const res = await fetch('/api/auth/config');
    const data = await res.json();
    $('google-login-group').style.display = data.google_oauth_enabled ? 'block' : 'none';
  } catch {
    // Sem conexão com a API ainda: mantém o botão do Google escondido em vez
    // de mostrar uma opção que pode não estar configurada.
  }
}

function requireAuth(): boolean {
  const token = localStorage.getItem('access_token');
  if (!token) {
    openAuthModal();
    return false;
  }
  return true;
}

function openAuthModal(): void {
  $('auth-modal').style.display = 'flex';
}

function showToast(message: string, type: 'success' | 'error' = 'success'): void {
  const container = $('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
}

function closeAuthModal(): void {
  $('auth-modal').style.display = 'none';
}

function toggleAuthMode(): void {
  authMode = authMode === 'login' ? 'register' : 'login';
  const isRegister = authMode === 'register';
  $('auth-modal-title').innerText = isRegister ? 'Criar Nova Conta 📝' : 'Acesso Restrito - Identifique-se 🔑';
  $('confirm-password-group').style.display = isRegister ? 'block' : 'none';
  $('btn-auth-submit').innerText = isRegister ? 'Cadastrar' : 'Entrar';
  $('auth-toggle-msg').innerText = isRegister ? 'Já possui uma conta?' : 'Não tem uma conta?';
  $('btn-toggle-auth').innerText = isRegister ? 'Fazer Login' : 'Cadastrar-se';
  $('auth-error-msg').style.display = 'none';
}

async function handleAuthSubmit(event: Event): Promise<void> {
  event.preventDefault();
  const email = $<HTMLInputElement>('auth-email').value;
  const password = $<HTMLInputElement>('auth-password').value;
  const confirmPassword = $<HTMLInputElement>('auth-password-confirm').value;
  const errorMsg = $('auth-error-msg');

  errorMsg.style.display = 'none';

  if (authMode === 'register' && password !== confirmPassword) {
    errorMsg.innerText = 'As senhas não coincidem!';
    errorMsg.style.display = 'block';
    return;
  }

  const endpoint = authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, password_confirm: confirmPassword })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Falha na autenticação.');
    }

    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('user_email', email);
    checkAuthSession();
  } catch (err: any) {
    errorMsg.innerText = err.message;
    errorMsg.style.display = 'block';
  }
}

function logout(): void {
  localStorage.removeItem('access_token');
  localStorage.removeItem('user_email');
  checkAuthSession();
}


// Inicialização do Mapa Leaflet
function initMap(): void {
  const mapElement = document.getElementById('map');
  if (!mapElement) return;

  map = L.map('map').setView([-15.7801, -47.9292], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap'
  }).addTo(map);

  map.on('click', (e: L.LeafletMouseEvent) => {
    selectedPoint = e.latlng;
    updateMapMarker();
    updateStepper();
  });
}

function updateMapMarker(): void {
  if (!selectedPoint) return;
  const dist = parseInt($<HTMLInputElement>('buffer-dist').value) || 5000;

  if (marker) map.removeLayer(marker);
  if (circleBuffer) map.removeLayer(circleBuffer);

  marker = L.marker([selectedPoint.lat, selectedPoint.lng]).addTo(map);
  circleBuffer = L.circle([selectedPoint.lat, selectedPoint.lng], {
    color: '#10b981',
    fillColor: '#10b981',
    fillOpacity: 0.2,
    radius: dist
  }).addTo(map);
}

// Alternar entre Abas da Aplicação
function switchTab(evt: Event | null, tabId: string): void {
  currentTab = tabId;
  document.querySelectorAll<HTMLElement>('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll<HTMLElement>('.tab-btn').forEach(el => el.classList.remove('active'));

  $(tabId).style.display = 'block';
  if (evt && evt.currentTarget) (evt.currentTarget as HTMLElement).classList.add('active');

  if (tabId === 'tab-sse') {
    loadSseMatrix();
  }
}

// Acessibilidade (Alto Contraste e Fonte) — preferências persistidas em
// localStorage para sobreviver a reloads e à navegação entre landing/app.
function setupAccessibility(): void {
  const contrastBtn = $('toggle-contrast');
  const fontUpBtn = $('font-size-up');
  const fontDownBtn = $('font-size-down');

  if (localStorage.getItem('high_contrast') === '1') {
    document.body.classList.add('high-contrast');
  }

  let currentFontSize = parseInt(localStorage.getItem('font_size') || '100', 10);
  document.body.style.fontSize = currentFontSize + '%';

  contrastBtn.addEventListener('click', () => {
    document.body.classList.toggle('high-contrast');
    localStorage.setItem('high_contrast', document.body.classList.contains('high-contrast') ? '1' : '0');
  });

  fontUpBtn.addEventListener('click', () => {
    currentFontSize = Math.min(130, currentFontSize + 10);
    document.body.style.fontSize = currentFontSize + '%';
    localStorage.setItem('font_size', String(currentFontSize));
  });

  fontDownBtn.addEventListener('click', () => {
    currentFontSize = Math.max(80, currentFontSize - 10);
    document.body.style.fontSize = currentFontSize + '%';
    localStorage.setItem('font_size', String(currentFontSize));
  });
}

// Alternar Campos da Área de Interesse
function toggleRoiInputs(): void {
  const type = $<HTMLSelectElement>('roi-type').value;
  $('point-inputs').style.display = type === 'point' ? 'block' : 'none';
  $('municipio-inputs').style.display = type === 'municipio' ? 'block' : 'none';
  if (type === 'point' && map) setTimeout(() => map.invalidateSize(), 200);
}

function toggleTifUpload(): void {
  const source = $<HTMLSelectElement>('data-source').value;
  $('geotiff-upload-group').style.display = source === 'geotiff' ? 'block' : 'none';
  $('gee-credentials-group').style.display = source === 'mapbiomas' ? 'block' : 'none';
}

// API IBGE (Estados e Municípios)
async function loadUfs(): Promise<void> {
  const select = $<HTMLSelectElement>('select-uf');
  try {
    const res = await fetch('https://servicodados.ibge.gov.br/api/v1/localidades/estados?ordenacao=nome');
    if (!res.ok) throw new Error('Resposta inválida da API do IBGE.');
    const ufs = await res.json();
    select.innerHTML = '<option value="">Selecione uma UF...</option>';
    ufs.forEach((uf: any) => {
      select.innerHTML += `<option value="${uf.sigla}">${uf.sigla} - ${uf.nome}</option>`;
    });
  } catch (err) {
    console.error('Erro ao buscar UFs:', err);
    select.innerHTML = '<option value="">Erro ao carregar estados</option>';
    showToast('Não foi possível carregar a lista de estados do IBGE. Recarregue a página.', 'error');
  }
}

async function loadMunicipios(): Promise<void> {
  const uf = $<HTMLSelectElement>('select-uf').value;
  const select = $<HTMLSelectElement>('select-municipio');
  if (!uf) return;
  select.innerHTML = '<option>Carregando municípios...</option>';
  try {
    const res = await fetch(`https://servicodados.ibge.gov.br/api/v1/localidades/estados/${uf}/municipios`);
    if (!res.ok) throw new Error('Resposta inválida da API do IBGE.');
    const munis = await res.json();
    select.innerHTML = '';
    munis.forEach((m: any) => {
      select.innerHTML += `<option value="${m.id}">${m.nome}</option>`;
    });
  } catch (err) {
    console.error('Erro ao buscar municípios:', err);
    select.innerHTML = '<option value="">Erro ao carregar municípios</option>';
    showToast('Não foi possível carregar os municípios desse estado.', 'error');
  }
}

// Credenciais do Earth Engine (obrigatórias para a fonte MapBiomas)
let hasGeeCredentials = false;

async function loadGeeCredentialsStatus(): Promise<void> {
  const statusEl = $('gee-credentials-status');
  if (!localStorage.getItem('access_token')) {
    statusEl.textContent = 'Faça login para cadastrar sua credencial do Earth Engine.';
    return;
  }
  try {
    const res = await fetch('/api/credentials/', { headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha ao verificar credenciais.');
    hasGeeCredentials = !!data.has_credentials;
    statusEl.textContent = hasGeeCredentials
      ? `✅ Credencial cadastrada (${data.client_email})`
      : '⚠️ Nenhuma credencial do Earth Engine cadastrada — obrigatória para usar a fonte MapBiomas.';
  } catch (err) {
    hasGeeCredentials = false;
    statusEl.textContent = 'Não foi possível verificar o status da credencial.';
  }
  updateStepper();
}

// Stepper do passo a passo (dados iniciais + parametrização) — acende cada
// passo conforme os campos exigidos por ele forem preenchidos, e só libera
// o botão de calcular quando os passos 1 e 2 estiverem completos.
function updateStepper(): void {
  const roiType = $<HTMLSelectElement>('roi-type').value;
  const step1Done = roiType === 'municipio'
    ? !!$<HTMLSelectElement>('select-municipio').value
    : !!selectedPoint;

  const dataSource = $<HTMLSelectElement>('data-source').value;
  const tifInput = document.getElementById('tif-file') as HTMLInputElement | null;
  const hasTif = !!(tifInput && tifInput.files && tifInput.files.length > 0);
  const step2Done = dataSource === 'mapbiomas' ? hasGeeCredentials : hasTif;

  const setStepState = (n: number, done: boolean, pendingLabel: string, doneLabel: string) => {
    const el = $(`step-${n}`);
    const number = $(`step-${n}-number`);
    const status = $(`step-${n}-status`);
    el.classList.toggle('done', done);
    el.classList.toggle('pending', !done);
    number.textContent = done ? '✓' : String(n);
    status.textContent = done ? doneLabel : pendingLabel;
  };

  setStepState(1, step1Done,
    'Dado inicial obrigatório — defina um ponto ou município.',
    'Área de interesse definida.');

  setStepState(2, step2Done,
    dataSource === 'mapbiomas'
      ? 'Parametrização obrigatória — cadastre sua credencial do Earth Engine.'
      : 'Parametrização obrigatória — envie um arquivo GeoTIFF.',
    'Fonte de dados parametrizada.');

  const step3Ready = step1Done && step2Done;
  $('step-3').classList.toggle('done', step3Ready);
  $('step-3').classList.toggle('pending', !step3Ready);
  $('step-3-status').textContent = step3Ready
    ? 'Tudo pronto — pode calcular.'
    : 'Disponível assim que os passos 1 e 2 estiverem completos.';
  ($('btn-compute') as HTMLButtonElement).disabled = !step3Ready;
}

async function saveGeeCredentials(): Promise<void> {
  if (!requireAuth()) return;
  const jsonText = $<HTMLTextAreaElement>('gee-credentials-json').value.trim();
  if (!jsonText) {
    showToast('Cole o JSON da credencial antes de salvar.', 'error');
    return;
  }
  try {
    const res = await fetch('/api/credentials/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ service_account_json: jsonText })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Credencial inválida.');
    showToast(data.message, 'success');
    $<HTMLTextAreaElement>('gee-credentials-json').value = '';
    $('gee-credentials-details').removeAttribute('open');
    loadGeeCredentialsStatus();
  } catch (err: any) {
    showToast(err.message, 'error');
  }
}

// Validação prévia dos campos obrigatórios, conforme modo de área/fonte
function validateAnalysisInputs(roiType: string, dataSource: string, tifFile: File | null): string | null {
  if (roiType === 'municipio' && !$<HTMLSelectElement>('select-municipio').value) {
    return 'Selecione um estado e um município antes de calcular.';
  }
  if (dataSource === 'mapbiomas') {
    if (roiType === 'point' && !selectedPoint) {
      return 'Clique no mapa para selecionar um ponto de interesse antes de calcular.';
    }
  } else if (dataSource === 'geotiff') {
    if (!tifFile) {
      return 'Envie um arquivo GeoTIFF antes de calcular.';
    }
  }
  return null;
}

// Execução da Análise de Paisagem (dados reais via /api/metrics/calculate)
async function runLandscapeAnalysis(): Promise<void> {
  if (!requireAuth()) return;

  const roiType = $<HTMLSelectElement>('roi-type').value;
  const dataSource = $<HTMLSelectElement>('data-source').value;
  const tifInput = $<HTMLInputElement>('tif-file');
  const tifFile = tifInput.files && tifInput.files[0] ? tifInput.files[0] : null;

  const validationError = validateAnalysisInputs(roiType, dataSource, tifFile);
  if (validationError) {
    showToast(validationError, 'error');
    return;
  }

  const button = $<HTMLButtonElement>('btn-compute');
  button.disabled = true;
  button.textContent = '⏳ Processando...';

  const formData = new FormData();
  formData.append('data_source', dataSource);

  if (roiType === 'municipio') {
    const ufSelect = $<HTMLSelectElement>('select-uf');
    const muniSelect = $<HTMLSelectElement>('select-municipio');
    formData.append('municipio_codigo', muniSelect.value);
    formData.append('municipio_nome', muniSelect.selectedOptions[0] ? muniSelect.selectedOptions[0].textContent || '' : '');
    formData.append('municipio_uf', ufSelect.value);
  } else if (selectedPoint) {
    formData.append('point_lon', String(selectedPoint.lng));
    formData.append('point_lat', String(selectedPoint.lat));
    formData.append('buffer_dist', $<HTMLInputElement>('buffer-dist').value);
  }

  if (dataSource === 'geotiff' && tifFile) {
    formData.append('tif_file', tifFile);
  }

  try {
    const res = await fetch('/api/metrics/calculate', {
      method: 'POST',
      headers: authHeaders(),
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Falha ao calcular métricas.');
    }

    $('results-placeholder').style.display = 'none';
    $('results-content').style.display = 'block';
    renderMetricsResult(data);
    showToast('Análise concluída com sucesso.', 'success');
  } catch (err: any) {
    showToast(err.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '🧮 Calcular Métricas da Paisagem';
  }
}

function renderMetricsResult(data: any): void {
  const lm = data.landscape_metrics || {};
  const fmt = (v: unknown) => (typeof v === 'number' ? v.toFixed(2) : '—');

  $('landscape-metrics-summary').innerHTML = `
    <div style="background: rgba(16,185,129,0.1); border: 1px solid var(--accent-emerald); padding: 1rem; border-radius: 8px;">
      <b>${data.label}</b>${data.ano ? ` (${data.ano})` : ''}<br>
      <b>SHDI (Diversidade de Shannon):</b> ${fmt(lm.shannon_diversity_index)} •
      <b>Densidade de manchas (PD):</b> ${fmt(lm.patch_density)} •
      <b>Densidade de borda (ED):</b> ${fmt(lm.edge_density)} m/ha
    </div>
  `;

  const classMetrics = data.class_metrics || {};
  const classNames = Object.keys(classMetrics);

  const tbody = document.querySelector('#metrics-table tbody') as HTMLTableSectionElement;
  tbody.innerHTML = '';
  classNames.forEach((cls) => {
    const row = classMetrics[cls];
    tbody.innerHTML += `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
        <td style="padding: 0.5rem 0;">${cls}</td>
        <td>${row.proportion_of_landscape != null ? row.proportion_of_landscape.toFixed(1) : '—'}%</td>
        <td>${row.number_of_patches != null ? row.number_of_patches : '—'}</td>
        <td>${row.edge_density != null ? row.edge_density.toFixed(1) : '—'} m/ha</td>
      </tr>
    `;
  });

  const ctx = ($('metrics-chart') as HTMLCanvasElement).getContext('2d');
  if (metricsChartInstance) metricsChartInstance.destroy();

  metricsChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: classNames,
      datasets: [{
        label: 'Proporção da Paisagem (%)',
        data: classNames.map((c) => classMetrics[c].proportion_of_landscape ?? 0),
        backgroundColor: '#10b981',
        borderRadius: 6
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.1)' } } }
    }
  });
}

// Matriz Socioecológica e Clustering API (dados reais)
async function loadSseMatrix(): Promise<void> {
  if (!requireAuth()) return;
  const head = $('sse-table-head');
  const body = $('sse-table-body');
  try {
    const res = await fetch('/api/sse/matrix', { headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha ao carregar a Matriz SSE.');

    if (!data.records || data.records.length === 0) {
      head.innerHTML = '<th>Nenhuma análise salva ainda — calcule uma análise na aba "Análise de Paisagem" para começar.</th>';
      body.innerHTML = '';
      return;
    }
    renderSseTable(data.records);
  } catch (err: any) {
    head.innerHTML = '<th>Não foi possível carregar a Matriz SSE</th>';
    body.innerHTML = '';
    showToast(err.message, 'error');
  }
}

function renderSseTable(records: Array<Record<string, any>>): void {
  const head = $('sse-table-head');
  const body = $('sse-table-body');
  if (!records || records.length === 0) return;

  const cols = Object.keys(records[0]);
  head.innerHTML = cols.map(c => `<th>${c}</th>`).join('');
  body.innerHTML = records.map(r => `
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
      ${cols.map(c => `<td style="padding: 0.5rem;">${r[c] !== null && r[c] !== undefined ? r[c] : '-'}</td>`).join('')}
    </tr>
  `).join('');
}

// Alternar Controles de Clustering
function toggleClusterControls(): void {
  const algo = $<HTMLSelectElement>('cluster-algo').value;
  $('kmeans-controls').style.display = algo === 'kmeans' ? 'block' : 'none';
  $('dbscan-controls').style.display = algo === 'dbscan' ? 'block' : 'none';
}

async function runClustering(): Promise<void> {
  if (!requireAuth()) return;
  const algo = $<HTMLSelectElement>('cluster-algo').value;

  try {
    const matrixRes = await fetch('/api/sse/matrix', { headers: authHeaders() });
    const matrixData = await matrixRes.json();
    if (!matrixRes.ok) throw new Error(matrixData.detail || 'Falha ao carregar a Matriz SSE.');

    const excluded = ['point_lon', 'point_lat', 'buffer_dist', 'ano'];
    const featureCols = (matrixData.numeric_columns || []).filter((c: string) => !excluded.includes(c));

    if (!matrixData.records || matrixData.records.length < 2 || featureCols.length === 0) {
      showToast('Salve ao menos 2 análises (com métricas numéricas) antes de executar um agrupamento.', 'error');
      return;
    }

    const endpoint = algo === 'kmeans' ? '/api/sse/cluster/kmeans' : '/api/sse/cluster/dbscan';
    const payload = algo === 'kmeans'
      ? { feature_cols: featureCols, k: parseInt($<HTMLInputElement>('input-k').value, 10) }
      : {
          feature_cols: featureCols,
          eps: parseFloat($<HTMLInputElement>('input-eps').value),
          min_samples: parseInt($<HTMLInputElement>('input-min-samples').value, 10)
        };

    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha ao executar o agrupamento.');

    renderClusterResult(algo, data);
    showToast(algo === 'kmeans' ? 'Agrupamento concluído com sucesso.' : 'Análise de densidade concluída.', 'success');
  } catch (err: any) {
    showToast(err.message, 'error');
  }
}

function renderClusterResult(algo: string, data: any): void {
  const clusterKey = algo === 'kmeans' ? 'cluster_kmeans' : 'cluster_dbscan';
  const pcaPoints: any[] = data.pca_data || [];

  const byCluster: Record<string, Array<{ x: number; y: number }>> = {};
  pcaPoints.forEach((p) => {
    const key = String(p[clusterKey]);
    if (!byCluster[key]) byCluster[key] = [];
    byCluster[key].push({ x: p.pca_1, y: p.pca_2 });
  });

  const palette = ['#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#eab308'];
  let colorIdx = 0;
  const datasets = Object.keys(byCluster).map((key) => {
    const color = key.startsWith('Outlier') ? '#ef4444' : palette[(colorIdx++) % palette.length];
    return { label: key, data: byCluster[key], backgroundColor: color, pointRadius: 8 };
  });

  const ctx = ($('pca-chart') as HTMLCanvasElement).getContext('2d');
  if (pcaChartInstance) pcaChartInstance.destroy();

  pcaChartInstance = new Chart(ctx, {
    type: 'scatter',
    data: { datasets },
    options: {
      responsive: true,
      scales: {
        x: { title: { display: true, text: 'Componente Principal 1 (PCA 1)', color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.1)' } },
        y: { title: { display: true, text: 'Componente Principal 2 (PCA 2)', color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.1)' } }
      }
    }
  });

  $('cluster-summary-info').innerText =
    algo === 'kmeans'
      ? `✅ K-Means concluído: ${data.k} cluster(s) formado(s) • Silhouette Score: ${data.silhouette != null ? data.silhouette.toFixed(3) : '—'}`
      : `✅ DBSCAN concluído: ${data.n_clusters} cluster(s) denso(s) • ${data.n_noise} outlier(s) identificado(s)`;
}

// Gestão de Avatares 3D e Onboarding
function toggleSpeechBubble(): void {
  const bubble = $('avatar-speech');
  bubble.style.display = bubble.style.display === 'none' ? 'block' : 'none';
}

function openOnboardingModal(): void {
  $('onboarding-modal').style.display = 'flex';
  $('step-0-selection').style.display = 'flex';
  $('step-tour-text').style.display = 'none';
  $('btn-next-step').style.display = 'none';
  currentTourStep = 0;
}

function closeOnboardingModal(): void {
  $('onboarding-modal').style.display = 'none';
}

function selectAvatar(avatarKey: AvatarKey): void {
  selectedAvatar = avatarKey;
  currentTourStep = 0;

  ($('avatar-widget-img') as HTMLImageElement).src = avatarKey === 'maria_julia' ? '/avatar_maria_julia.png' : '/avatar_pedro.png';
  $('step-0-selection').style.display = 'none';
  $('step-tour-text').style.display = 'block';
  $('btn-next-step').style.display = 'inline-block';

  renderTourStep();
}

function renderTourStep(): void {
  const steps = tourSteps[selectedAvatar];
  const step = steps[currentTourStep];

  $('tour-step-title').innerText = step.title;
  $('step-tour-text').innerText = step.text;
  $('speech-text').innerText = step.text;
}

function nextTourStep(): void {
  const steps = tourSteps[selectedAvatar];
  currentTourStep++;
  if (currentTourStep >= steps.length) {
    closeOnboardingModal();
    $('avatar-speech').style.display = 'block';
  } else {
    renderTourStep();
  }
}

// Exportação e Exclusão LGPD (dados reais via /api/lgpd)
async function exportUserData(): Promise<void> {
  if (!requireAuth()) return;
  try {
    const res = await fetch('/api/lgpd/export', { headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha ao exportar seus dados.');

    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(data, null, 2));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", "dados_lgpd_portabilidade.json");
    dlAnchorElem.click();
    showToast('Seu arquivo de exportação foi preparado.', 'success');
  } catch (err: any) {
    showToast(err.message, 'error');
  }
}

async function deleteUserAccount(): Promise<void> {
  if (!requireAuth()) return;
  if (!confirm("Tem certeza que deseja solicitar a eliminação dos seus dados conforme o Art. 18 da LGPD? Esta ação é irreversível.")) {
    return;
  }

  try {
    const res = await fetch('/api/lgpd/account', { method: 'DELETE', headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Falha ao processar a exclusão.');

    showToast(data.message, 'success');
    alert(`${data.message}\nProtocolo: ${data.protocolo_exclusao}`);
    logout();
  } catch (err: any) {
    showToast(err.message, 'error');
  }
}

// ============================================================================
// Predição via Cadeias de Markov
// ============================================================================

let markovChartInstance: any = null;

function toggleMarkovRoiInputs(): void {
  const type = $<HTMLSelectElement>('markov-roi-type').value;
  $('markov-point-inputs').style.display = type === 'point' ? 'block' : 'none';
  $('markov-municipio-inputs').style.display = type === 'municipio' ? 'block' : 'none';
}

async function runMarkovPrediction(event: Event): Promise<void> {
  event.preventDefault();
  if (!requireAuth()) return;

  const btn = $<HTMLButtonElement>('btn-markov-submit');
  const fileInput = $<HTMLInputElement>('markov-tif-files');
  const roiType = $<HTMLSelectElement>('markov-roi-type').value;
  const targetYears = $<HTMLInputElement>('markov-target-years').value;

  if (!fileInput.files || fileInput.files.length < 2) {
    showToast('Selecione pelo menos 2 arquivos GeoTIFF.', 'error');
    return;
  }

  const formData = new FormData();
  for (let i = 0; i < fileInput.files.length; i++) {
    formData.append('tif_files', fileInput.files[i]);
  }
  formData.append('target_years', targetYears);

  if (roiType === 'point') {
    formData.append('point_lon', $<HTMLInputElement>('markov-lon').value);
    formData.append('point_lat', $<HTMLInputElement>('markov-lat').value);
    formData.append('buffer_dist', $<HTMLInputElement>('markov-buffer').value);
  } else if (roiType === 'municipio') {
    formData.append('municipio_codigo', $<HTMLInputElement>('markov-municipio-codigo').value);
  }

  btn.disabled = true;
  btn.textContent = '⏳ Processando predição (pode demorar)...';

  try {
    const res = await fetch('/api/markov/predict', {
      method: 'POST',
      headers: authHeaders(),
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Falha ao executar predição de Markov.');
    }
    
    $('markov-results').style.display = 'block';
    renderMarkovResults(data);
    showToast('Predição gerada com sucesso!', 'success');
  } catch (err: any) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Gerar Predição';
  }
}

function renderMarkovResults(data: any): void {
  const { historico, predicoes, matriz_transicao, anos_alvo, ultimo_ano_observado, classes_mapbiomas } = data;
  
  // Render Chart
  const ctx = ($('markov-chart') as HTMLCanvasElement).getContext('2d');
  if (markovChartInstance) markovChartInstance.destroy();
  
  const allYears = [...historico.map((h: any) => h.ano), ...anos_alvo];
  // Gather all unique classes
  const classes = new Set<string>();
  historico.forEach((h: any) => Object.keys(h.proporcoes).forEach(c => classes.add(c)));
  Object.values(predicoes).forEach((p: any) => Object.keys(p).forEach(c => classes.add(c)));
  
  const datasets = Array.from(classes).map((cls, i) => {
    const clsName = classes_mapbiomas[cls] || `Classe ${cls}`;
    const dataPoints = allYears.map(y => {
      const hist = historico.find((h: any) => h.ano === y);
      if (hist) return (hist.proporcoes[cls] || 0) * 100;
      const pred = predicoes[y];
      if (pred) return (pred[cls] || 0) * 100;
      return 0;
    });
    
    // generate some colors
    const colors = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#eab308'];
    return {
      label: clsName,
      data: dataPoints,
      borderColor: colors[i % colors.length],
      backgroundColor: colors[i % colors.length] + '33',
      fill: false,
      tension: 0.1
    };
  });
  
  markovChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: allYears,
      datasets: datasets
    },
    options: {
      responsive: true,
      plugins: {
        tooltip: {
          callbacks: {
            label: function(context: any) {
              return context.dataset.label + ': ' + context.parsed.y.toFixed(1) + '%';
            }
          }
        }
      },
      scales: {
        y: {
          title: { display: true, text: 'Proporção (%)' },
          beginAtZero: true
        }
      }
    }
  });
  
  // Render Transition Matrix Table
  const head = $('markov-table-head');
  const body = $('markov-table-body');
  
  const classesList = Object.keys(matriz_transicao);
  head.innerHTML = '<th>De \\ Para</th>' + classesList.map(c => `<th>${classes_mapbiomas[c] || c}</th>`).join('');
  
  body.innerHTML = classesList.map(rowClass => {
    const row = matriz_transicao[rowClass];
    return `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
        <td><strong>${classes_mapbiomas[rowClass] || rowClass}</strong></td>
        ${classesList.map(colClass => `<td>${row[colClass] !== undefined ? row[colClass].toFixed(4) : '0.0000'}</td>`).join('')}
      </tr>
    `;
  }).join('');
}
