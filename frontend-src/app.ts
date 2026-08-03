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
let deferredPrompt: any = null;

// Última Matriz SSE carregada (GET /api/sse/matrix) — guardada em memória só
// para alimentar as exportações .xlsx (exportSseMatrixToExcel/
// exportClusterToExcel) sem precisar buscar de novo no backend.
let lastSseMatrix: { records: any[]; columns: string[]; numeric_columns: string[] } | null = null;

// ============================================================================
// Wizard de 5 etapas (Área & Contexto → Fonte de Dados → Métricas →
// Análise Avançada → Síntese & Exportação) — o pipeline em si continua
// sendo as mesmas abas/rotas de sempre; o wizard só adiciona um estado
// compartilhado (pipelineState) que trava as abas avançadas até a Etapa 3
// terminar, e usa a saída da Etapa 3 como insumo (prefill) da Etapa 4.
// ============================================================================

// Abas que só fazem sentido depois de pelo menos uma análise de métricas
// calculada nesta sessão (ou já existente no histórico do usuário).
const ADVANCED_TABS = ['tab-sse', 'tab-markov', 'tab-municipio-batch', 'tab-sintese'];

interface PipelineContext {
  roiType: string;
  municipioCodigo?: string;
  pointLon?: number;
  pointLat?: number;
  bufferDist?: number;
}

interface PipelineState {
  hasMetrics: boolean;
  lastMetrics: any | null;
  lastContext: PipelineContext | null;
  lastMarkov: any | null;
  lastCluster: { algo: 'kmeans' | 'dbscan'; data: any } | null;
  lastMunicipioBatch: any | null;
}

const pipelineState: PipelineState = {
  hasMetrics: false,
  lastMetrics: null,
  lastContext: null,
  lastMarkov: null,
  lastCluster: null,
  lastMunicipioBatch: null,
};

// Espelham o resultado de updateStepper() (etapas 1/2 locais da aba de
// análise) para o wizard global conseguir refletir o mesmo estado sem
// recalcular a lógica de campos obrigatórios duas vezes.
let step1Done = false;
let step2Done = false;

function isTabLocked(tabId: string): boolean {
  return ADVANCED_TABS.includes(tabId) && !pipelineState.hasMetrics;
}

// Acende/apaga o cadeado visual nos itens do menu lateral que dependem da
// Etapa 3 já ter rodado — chamado sempre que pipelineState.hasMetrics muda.
function updateNavLocks(): void {
  ADVANCED_TABS.forEach((tabId) => {
    const btn = document.querySelector(`.sidebar .tab-btn[data-tab="${tabId}"]`);
    if (btn) btn.classList.toggle('locked', !pipelineState.hasMetrics);
  });
}

// Atualiza os 5 "pills" do wizard global (#global-wizard): done = etapa já
// concluída nesta sessão, active = etapa correspondente à aba aberta agora,
// locked = etapas 4/5 antes da primeira análise de métricas.
function updateGlobalWizard(): void {
  const step4Done = !!(pipelineState.lastMarkov || pipelineState.lastCluster || pipelineState.lastMunicipioBatch);
  const doneByStep: Record<number, boolean> = {
    1: step1Done,
    2: step2Done,
    3: pipelineState.hasMetrics,
    4: step4Done,
    5: false,
  };
  const lockedByStep: Record<number, boolean> = {
    1: false,
    2: false,
    3: false,
    4: !pipelineState.hasMetrics,
    5: !pipelineState.hasMetrics,
  };
  const activeStepByTab: Record<string, number> = {
    'tab-analise': step1Done && step2Done ? 3 : (step1Done ? 2 : 1),
    'tab-sse': 4,
    'tab-markov': 4,
    'tab-municipio-batch': 4,
    'tab-sintese': 5,
  };
  const activeStep = activeStepByTab[currentTab] ?? 0;

  for (let n = 1; n <= 5; n++) {
    const pill = document.getElementById(`wizard-step-${n}`);
    if (!pill) continue;
    pill.classList.toggle('done', doneByStep[n]);
    pill.classList.toggle('locked', lockedByStep[n]);
    pill.classList.toggle('active', n === activeStep);
  }
}

// Clique num "pill" do wizard global — pula direto para a aba daquela etapa
// (etapas 1-3 vivem todas em tab-analise; 4 abre o último módulo avançado
// usado, ou Markov por padrão; 5 é a síntese).
function goToWizardStep(n: number): void {
  const lastAdvancedTab = currentTab === 'tab-sse' || currentTab === 'tab-municipio-batch' ? currentTab : 'tab-markov';
  const tabByStep: Record<number, string> = {
    1: 'tab-analise', 2: 'tab-analise', 3: 'tab-analise', 4: lastAdvancedTab, 5: 'tab-sintese',
  };
  const tabId = tabByStep[n];
  if (isTabLocked(tabId)) {
    showToast('Calcule uma análise de paisagem na Etapa 3 antes de acessar esta etapa.', 'error');
    return;
  }
  const btn = document.querySelector<HTMLElement>(`.sidebar .tab-btn[data-tab="${tabId}"]`);
  if (btn) btn.click();
  else switchTab(null, tabId);
}

// Usada pelo painel "Etapa 4" que aparece junto do resultado das métricas —
// além de navegar, repassa o contexto (município ou ponto+buffer) da última
// análise calculada para o módulo avançado escolhido, evitando que o
// usuário redigite os mesmos parâmetros na Etapa 4.
function goToAdvancedStep(tabId: string): void {
  prefillAdvancedFromLastContext(tabId);
  const btn = document.querySelector<HTMLElement>(`.sidebar .tab-btn[data-tab="${tabId}"]`);
  if (btn) btn.click();
  else switchTab(null, tabId);
}

function prefillAdvancedFromLastContext(tabId: string): void {
  const ctx = pipelineState.lastContext;
  if (!ctx || tabId !== 'tab-markov') return;

  if (ctx.roiType === 'municipio' && ctx.municipioCodigo) {
    ($('markov-roi-type') as HTMLSelectElement).value = 'municipio';
    toggleMarkovRoiInputs();
    $<HTMLInputElement>('markov-municipio-codigo').value = ctx.municipioCodigo;
  } else if (ctx.roiType === 'point' && ctx.pointLon !== undefined && ctx.pointLat !== undefined) {
    ($('markov-roi-type') as HTMLSelectElement).value = 'point';
    toggleMarkovRoiInputs();
    $<HTMLInputElement>('markov-lon').value = String(ctx.pointLon);
    $<HTMLInputElement>('markov-lat').value = String(ctx.pointLat);
    $<HTMLInputElement>('markov-buffer').value = String(ctx.bufferDist ?? 5000);
  }
}

// Um usuário que já tem análises salvas de sessões anteriores não deveria
// ver a Etapa 4/5 travada de novo só por ter recarregado a página — checa o
// histórico já persistido (mesma fonte da Matriz SSE) uma vez após o login.
async function refreshHistoryUnlock(): Promise<void> {
  if (!accessToken) return;
  try {
    const res = await fetch('/api/metrics/history', { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    if (Array.isArray(data) && data.length > 0) {
      pipelineState.hasMetrics = true;
    }
  } catch {
    // silencioso — sem histórico carregado, o usuário ainda libera a Etapa 4
    // normalmente ao calcular uma análise nova na Etapa 3.
  } finally {
    updateNavLocks();
    updateGlobalWizard();
  }
}

function renderSynthesis(): void {
  const empty = $('sintese-empty');
  const content = $('sintese-content');
  if (!pipelineState.lastMetrics) {
    empty.style.display = 'block';
    content.style.display = 'none';
    return;
  }
  empty.style.display = 'none';
  content.style.display = 'block';

  const m = pipelineState.lastMetrics;
  const lm = m.landscape_metrics || {};
  const fmt = (v: unknown) => (typeof v === 'number' ? v.toFixed(2) : '—');
  $('sintese-metrics-card').innerHTML = `
    <div style="font-weight:700; margin-bottom:0.35rem;">📍 Métricas de paisagem (Etapa 3)</div>
    <div><b>${m.label ?? ''}</b>${m.ano ? ` (${m.ano})` : ''}</div>
    <div>SHDI: ${fmt(lm.shannon_diversity_index)} • Densidade de manchas: ${fmt(lm.patch_density)} • Densidade de borda: ${fmt(lm.edge_density)} m/ha</div>
  `;

  const markovCard = $('sintese-markov-card');
  if (pipelineState.lastMarkov) {
    const md = pipelineState.lastMarkov;
    markovCard.style.display = 'block';
    markovCard.innerHTML = `
      <div style="font-weight:700; margin-bottom:0.35rem;">🔮 Predição (Markov)</div>
      <div>Último ano observado: ${md.ultimo_ano_observado} • Anos projetados: ${(md.anos_alvo || []).join(', ')}</div>
    `;
  } else {
    markovCard.style.display = 'none';
  }

  const clusterCard = $('sintese-cluster-card');
  if (pipelineState.lastCluster) {
    const { algo, data } = pipelineState.lastCluster;
    clusterCard.style.display = 'block';
    clusterCard.innerHTML = algo === 'kmeans'
      ? `<div style="font-weight:700; margin-bottom:0.35rem;">🧬 Agrupamento (K-Means)</div><div>${data.k} cluster(s) • Silhouette: ${data.silhouette != null ? data.silhouette.toFixed(3) : '—'}</div>`
      : `<div style="font-weight:700; margin-bottom:0.35rem;">🧬 Agrupamento (DBSCAN)</div><div>${data.n_clusters} cluster(s) • ${data.n_noise} outlier(s)</div>`;
  } else {
    clusterCard.style.display = 'none';
  }

  const batchCard = $('sintese-batch-card');
  if (pipelineState.lastMunicipioBatch) {
    const b = pipelineState.lastMunicipioBatch;
    batchCard.style.display = 'block';
    const erroCount = (b.erros || []).length;
    batchCard.innerHTML = `
      <div style="font-weight:700; margin-bottom:0.35rem;">📦 Lote por município</div>
      <div>${b.sucesso}/${b.total_municipios} município(s) processado(s)${erroCount ? ` • ${erroCount} com erro` : ''}</div>
    `;
  } else {
    batchCard.style.display = 'none';
  }
}

function downloadSynthesis(): void {
  const payload = {
    gerado_em: new Date().toISOString(),
    metricas: pipelineState.lastMetrics,
    markov: pipelineState.lastMarkov,
    clustering: pipelineState.lastCluster,
    lote_municipio: pipelineState.lastMunicipioBatch,
  };
  const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(payload, null, 2));
  const anchor = document.createElement('a');
  anchor.setAttribute('href', dataStr);
  anchor.setAttribute('download', 'sintese_analise.json');
  anchor.click();
  showToast('Síntese exportada em JSON.', 'success');
}



// Registro de PWA Service Worker e Prompt de Instalação
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

// --- BYPASS TEMPORÁRIO DE LOGIN (pedido em 2026-07-30, para rodar cálculos
// reais sem fricção de login) — deixe null para restaurar o fluxo normal.
// Espelha backend/.env::dev_auth_bypass_email (ver backend/app/api/deps.py)
// — o backend aceita qualquer token enquanto esse bypass estiver ativo lá,
// então o valor de accessToken aqui não precisa ser um JWT de verdade.
const DEV_BYPASS_EMAIL: string | null = 'ederbtos@gmail.com';

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
  if (DEV_BYPASS_EMAIL) {
    accessToken = 'dev-bypass';
    const bypassContainer = $('user-session-container');
    const bypassShell = $('app-shell');
    bypassContainer.innerHTML = `<span style="font-size: 0.85rem; color: var(--accent-emerald); font-weight: 600;">👤 ${DEV_BYPASS_EMAIL} (login temporariamente desativado)</span>`;
    closeAuthModal();
    bypassShell.style.display = 'flex';
    loadGeeCredentialsStatus();
    updateStepper();
    refreshHistoryUnlock();
    return;
  }

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
    refreshHistoryUnlock();
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
  if (!accessToken) {
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
  if ($('lgpd-consent-group')) $('lgpd-consent-group').style.display = isRegister ? 'flex' : 'none';
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
  
  if (authMode === 'register') {
    const lgpdConsent = $<HTMLInputElement>('auth-lgpd-consent');
    if (lgpdConsent && !lgpdConsent.checked) {
        errorMsg.innerText = 'É necessário aceitar os Termos de Uso e Política de Privacidade.';
        errorMsg.style.display = 'block';
        return;
    }
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

    accessToken = data.access_token;
    localStorage.setItem('user_email', email);
    
    // LGPD: Registrar o consentimento no backend
    if (authMode === 'register') {
        try {
            await fetch('/api/lgpd/consent', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`
                },
                body: JSON.stringify({ term_version: 'v1.0', accepted: true })
            });
        } catch (e) {
            console.error('Falha ao gravar trilha LGPD', e);
        }
    }

    checkAuthSession();
  } catch (err: any) {
    errorMsg.innerText = err.message;
    errorMsg.style.display = 'block';
  }
}

// Precisa chamar o backend (não só limpar o estado local) para revogar o
// refresh token — sem isso, o cookie httpOnly continuaria válido e a
// próxima checkAuthSession (ex.: ao recarregar a página) usaria
// _tryRefreshAccessToken pra logar o usuário de volta silenciosamente,
// tornando "Sair" inofensivo agora que o access token só vive em memória.
async function logout(): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  } catch {
    // segue limpando o estado local mesmo se a chamada falhar
  }
  accessToken = null;
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
  if (isTabLocked(tabId)) {
    if (evt) evt.preventDefault();
    showToast('Calcule uma análise de paisagem na Etapa 3 antes de acessar esta etapa.', 'error');
    return;
  }

  currentTab = tabId;
  document.querySelectorAll<HTMLElement>('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll<HTMLElement>('.tab-btn').forEach(el => el.classList.remove('active'));

  $(tabId).style.display = 'block';
  if (evt && evt.currentTarget) (evt.currentTarget as HTMLElement).classList.add('active');
  else {
    const btn = document.querySelector<HTMLElement>(`.sidebar .tab-btn[data-tab="${tabId}"]`);
    if (btn) btn.classList.add('active');
  }

  if (tabId === 'tab-sse') {
    loadSseMatrix();
  } else if (tabId === 'tab-sintese') {
    renderSynthesis();
  }

  updateGlobalWizard();
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
  $('shapefile-inputs').style.display = type === 'shapefile' ? 'block' : 'none';
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
  if (!accessToken) {
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
  if (roiType === 'municipio') {
    step1Done = !!$<HTMLSelectElement>('select-municipio').value;
  } else if (roiType === 'shapefile') {
    const shpInput = document.getElementById('roi-shp-files') as HTMLInputElement | null;
    step1Done = !!(shpInput && shpInput.files && shpInput.files.length > 0);
  } else {
    step1Done = !!selectedPoint;
  }

  const dataSource = $<HTMLSelectElement>('data-source').value;
  const tifInput = document.getElementById('tif-file') as HTMLInputElement | null;
  const hasTif = !!(tifInput && tifInput.files && tifInput.files.length > 0);
  step2Done = dataSource === 'mapbiomas' ? hasGeeCredentials : hasTif;

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

  updateGlobalWizard();
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
  if (roiType === 'shapefile') {
    const shpInput = $<HTMLInputElement>('roi-shp-files');
    if (!shpInput.files || shpInput.files.length === 0) {
      return 'Envie o shapefile da área (.zip/.geojson ou os componentes .shp/.shx/.dbf) antes de calcular.';
    }
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

  let contextForPrefill: PipelineContext;
  if (roiType === 'municipio') {
    const ufSelect = $<HTMLSelectElement>('select-uf');
    const muniSelect = $<HTMLSelectElement>('select-municipio');
    formData.append('municipio_codigo', muniSelect.value);
    formData.append('municipio_nome', muniSelect.selectedOptions[0] ? muniSelect.selectedOptions[0].textContent || '' : '');
    formData.append('municipio_uf', ufSelect.value);
    contextForPrefill = { roiType, municipioCodigo: muniSelect.value };
  } else if (roiType === 'shapefile') {
    const shpFiles = $<HTMLInputElement>('roi-shp-files').files;
    if (shpFiles) {
      for (let i = 0; i < shpFiles.length; i++) {
        formData.append('shp_files', shpFiles[i]);
      }
    }
    contextForPrefill = { roiType };
  } else if (selectedPoint) {
    formData.append('point_lon', String(selectedPoint.lng));
    formData.append('point_lat', String(selectedPoint.lat));
    formData.append('buffer_dist', $<HTMLInputElement>('buffer-dist').value);
    contextForPrefill = {
      roiType,
      pointLon: selectedPoint.lng,
      pointLat: selectedPoint.lat,
      bufferDist: parseFloat($<HTMLInputElement>('buffer-dist').value),
    };
  } else {
    contextForPrefill = { roiType };
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

    pipelineState.hasMetrics = true;
    pipelineState.lastMetrics = data;
    pipelineState.lastContext = contextForPrefill;
    $('next-steps-panel').style.display = 'block';
    updateNavLocks();
    updateGlobalWizard();

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

  let climateHtml = '';
  if (data.climate_data) {
    if (data.climate_data.error) {
      climateHtml = `<br><span style="color:#ef4444; font-size:0.9em;">⚠️ Precipitação: Indisponível (${data.climate_data.error})</span>`;
    } else {
      climateHtml = `<br><b>🌧️ Precipitação Pluviométrica Anual (${data.climate_data.year}):</b> ${data.climate_data.total_precipitation_mm.toFixed(2)} mm <i><small>(Fonte: ${data.climate_data.source})</small></i>`;
    }
  }

  $('landscape-metrics-summary').innerHTML = `
    <div style="background: rgba(16,185,129,0.1); border: 1px solid var(--accent-emerald); padding: 1rem; border-radius: 8px;">
      <b>${data.label}</b>${data.ano ? ` (${data.ano})` : ''}<br>
      <b>SHDI (Diversidade de Shannon):</b> ${fmt(lm.shannon_diversity_index)} •
      <b>Densidade de manchas (PD):</b> ${fmt(lm.patch_density)} •
      <b>Densidade de borda (ED):</b> ${fmt(lm.edge_density)} m/ha
      ${climateHtml}
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

    lastSseMatrix = data;
    $<HTMLButtonElement>('btn-export-matrix-excel').style.display = data.records && data.records.length > 0 ? 'inline-block' : 'none';

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

// Exporta a Matriz SSE (base de dados por trás do agrupamento) para .xlsx,
// pronta para gráficos no Excel — gerado 100% no navegador via SheetJS
// (CDN, ver index.html), sem chamada nova ao backend.
function exportSseMatrixToExcel(): void {
  if (!lastSseMatrix || !lastSseMatrix.records || lastSseMatrix.records.length === 0) {
    showToast('Carregue a Matriz SSE (com ao menos uma análise salva) antes de exportar.', 'error');
    return;
  }
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(lastSseMatrix.records), 'Matriz_SSE');
  XLSX.writeFile(wb, `matriz_sse_${new Date().toISOString().slice(0, 10)}.xlsx`);
  showToast('Matriz exportada — abra no Excel para montar o gráfico.', 'success');
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
    lastSseMatrix = matrixData;
    $<HTMLButtonElement>('btn-export-matrix-excel').style.display = matrixData.records && matrixData.records.length > 0 ? 'inline-block' : 'none';

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
    pipelineState.lastCluster = { algo: algo as 'kmeans' | 'dbscan', data };
    updateGlobalWizard();
    $<HTMLButtonElement>('btn-export-cluster-excel').style.display = 'inline-block';
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

// Exporta o resultado do agrupamento (pontos PCA rotulados por cluster,
// perfis médios por cluster e, no K-Means, a curva do cotovelo) para .xlsx —
// cada aba já pronta para virar um gráfico no Excel (dispersão PCA×cluster,
// barras por perfil, linha da curva do cotovelo). Gerado 100% no navegador
// via SheetJS (CDN, ver index.html), sem chamada nova ao backend.
function exportClusterToExcel(): void {
  if (!pipelineState.lastCluster) {
    showToast('Execute um agrupamento (K-Means ou DBSCAN) antes de exportar.', 'error');
    return;
  }
  const { algo, data } = pipelineState.lastCluster;
  const wb = XLSX.utils.book_new();

  const pcaRows: any[] = data.pca_data || [];
  if (pcaRows.length > 0) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(pcaRows), 'PCA_Clusters');
  }

  const profiles = data.cluster_profiles || {};
  const profileRows = Object.keys(profiles).map((clusterKey) => ({ cluster: clusterKey, ...profiles[clusterKey] }));
  if (profileRows.length > 0) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(profileRows), 'Perfis_Cluster');
  }

  if (algo === 'kmeans' && Array.isArray(data.elbow_curve) && data.elbow_curve.length > 0) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.elbow_curve), 'Curva_Cotovelo');
  }

  if (lastSseMatrix && lastSseMatrix.records && lastSseMatrix.records.length > 0) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(lastSseMatrix.records), 'Matriz_SSE_Base');
  }

  if (wb.SheetNames.length === 0) {
    showToast('Nada para exportar neste resultado de agrupamento.', 'error');
    return;
  }

  XLSX.writeFile(wb, `agrupamento_${algo}_${new Date().toISOString().slice(0, 10)}.xlsx`);
  showToast('Planilha exportada — abra no Excel para montar o gráfico.', 'success');
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
  $('markov-shapefile-inputs').style.display = type === 'shapefile' ? 'block' : 'none';
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

  if (roiType === 'shapefile') {
    const shpFiles = $<HTMLInputElement>('markov-shp-files').files;
    if (!shpFiles || shpFiles.length === 0) {
      showToast('Envie o shapefile da área (.zip/.geojson ou os componentes .shp/.shx/.dbf) antes de gerar a predição.', 'error');
      return;
    }
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
  } else if (roiType === 'shapefile') {
    const shpFiles = $<HTMLInputElement>('markov-shp-files').files;
    if (shpFiles) {
      for (let i = 0; i < shpFiles.length; i++) {
        formData.append('shp_files', shpFiles[i]);
      }
    }
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
    pipelineState.lastMarkov = data;
    updateGlobalWizard();
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

// Métricas por Município em Lote (shapefile de municípios + 1 GeoTIFF)
async function runMunicipioBatch(event: Event): Promise<void> {
  event.preventDefault();
  if (!requireAuth()) return;

  const btn = $<HTMLButtonElement>('btn-municipio-batch-submit');
  const shpInput = $<HTMLInputElement>('municipio-batch-shp-files');
  const tifInput = $<HTMLInputElement>('municipio-batch-tif-file');

  if (!shpInput.files || shpInput.files.length === 0) {
    showToast('Selecione o(s) arquivo(s) do shapefile de municípios.', 'error');
    return;
  }
  if (!tifInput.files || tifInput.files.length !== 1) {
    showToast('Selecione um único arquivo GeoTIFF.', 'error');
    return;
  }

  const formData = new FormData();
  for (let i = 0; i < shpInput.files.length; i++) {
    formData.append('municipio_files', shpInput.files[i]);
  }
  formData.append('tif_file', tifInput.files[0]);

  const codeCol = $<HTMLInputElement>('municipio-batch-code-col').value.trim();
  const nameCol = $<HTMLInputElement>('municipio-batch-name-col').value.trim();
  const ufCol = $<HTMLInputElement>('municipio-batch-uf-col').value.trim();
  if (codeCol) formData.append('code_col', codeCol);
  if (nameCol) formData.append('name_col', nameCol);
  if (ufCol) formData.append('uf_col', ufCol);

  btn.disabled = true;
  btn.textContent = '⏳ Processando lote (pode demorar bastante)...';

  try {
    const res = await fetch('/api/municipio-batch/run', {
      method: 'POST',
      headers: authHeaders(),
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Falha ao processar o lote de municípios.');
    }

    $('municipio-batch-results').style.display = 'block';
    renderMunicipioBatchResults(data);
    pipelineState.lastMunicipioBatch = data;
    updateGlobalWizard();
    showToast(`Lote concluído: ${data.sucesso}/${data.total_municipios} municípios processados.`, 'success');
  } catch (err: any) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Calcular Lote';
  }
}

function renderMunicipioBatchResults(data: any): void {
  const summary = $('municipio-batch-summary');
  const head = $('municipio-batch-table-head');
  const body = $('municipio-batch-table-body');

  const erroCount = (data.erros || []).length;
  summary.innerHTML = `
    <div style="background: rgba(16,185,129,0.1); border: 1px solid var(--accent-emerald); padding: 1rem; border-radius: 8px;">
      <b>${data.sucesso}</b> de <b>${data.total_municipios}</b> municípios processados com sucesso
      ${erroCount > 0 ? ` • <span style="color: #ef4444;">${erroCount} com erro</span>` : ''}
    </div>
  `;

  const rows: any[] = data.landscape_rows || [];
  if (rows.length === 0) {
    head.innerHTML = '<th>Nenhum município processado com sucesso</th>';
    body.innerHTML = '';
    return;
  }

  const cols = Object.keys(rows[0]);
  head.innerHTML = cols.map(c => `<th>${c}</th>`).join('');
  body.innerHTML = rows.map(r => `
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
      ${cols.map(c => {
        const v = r[c];
        const display = typeof v === 'number' ? v.toFixed(2) : (v !== null && v !== undefined ? v : '-');
        return `<td style="padding: 0.5rem;">${display}</td>`;
      }).join('')}
    </tr>
  `).join('');
}

/* ==========================================================================
   Intelligent Help System (Avatars & Onboarding)
   ========================================================================== */

let selectedAvatarId: string | null = null;
let currentTourStep = 0;

const AVATAR_PROFILES: any = {
  'maria_julia': {
    name: 'Maria Júlia',
    img: '/avatar_maria_julia.png',
    greetings: 'Olá! Sou a Maria Júlia. Vou te guiar na interpretação ecológica das nossas métricas!',
    tips: {
      'tab-analise': 'Aqui começamos! Defina sua área de estudo (ponto, município ou shapefile) e a fonte de dados (MapBiomas ou seu próprio GeoTIFF).',
      'tab-sse': 'A Matriz Socioecológica (SSE) permite integrar fatores sociais e biofísicos. Muito útil para planejamento regional!',
      'tab-markov': 'As Cadeias de Markov nos ajudam a prever cenários futuros de uso do solo com base no histórico recente.',
      'tab-municipio-batch': 'Quer analisar o estado todo? Envie o shapefile dos municípios e nós rodamos a paisagem em lote!',
      'tab-sintese': 'Pronto para o relatório final? Exporte suas métricas para um mapa visual ou PDF amigável.'
    }
  },
  'pedro': {
    name: 'Pedro',
    img: '/avatar_pedro.png',
    greetings: 'E aí! Sou o Pedro. Vou focar na arquitetura de dados e otimização das suas análises espaciais.',
    tips: {
      'tab-analise': 'Selecione o ROI e a Fonte de Dados. Se for usar o MapBiomas, certifique-se de que sua credencial JSON do Earth Engine está vinculada.',
      'tab-sse': 'Esta matriz agrupa os dados de saída do pipeline. Use o K-Means e DBSCAN para clusterização avançada.',
      'tab-markov': 'Matriz de Transição e predição estocástica via Cadeias de Markov. O gráfico gerado cruza dados históricos com os anos alvo.',
      'tab-municipio-batch': 'Processamento massivo em lote. Insira o SHP com a malha municipal e o GeoTIFF cobrindo a região. O worker cuida do resto.',
      'tab-sintese': 'Os DataFrames gerados estão prontos para exportação. Clique nos botões para baixar os arquivos vetoriais ou raster.'
    }
  }
};

const TOUR_STEPS = [
  { title: 'Bem-vindo ao LandscapeMetrics! 🌍', text: 'Eu serei o seu guia.' },
  { title: 'Passo 1: Área de Interesse 📍', text: 'Tudo começa na aba "Análise". Você pode clicar no mapa para definir um ponto, escolher um município ou subir um arquivo Shapefile (.zip).' },
  { title: 'Passo 2: Fonte de Dados 🛰️', text: 'Você pode extrair dados diretamente do MapBiomas (usando o Google Earth Engine) ou subir seu próprio mapa raster (GeoTIFF).' },
  { title: 'Pronto para explorar! 🚀', text: 'Sempre que tiver dúvidas, clique em mim aqui no canto inferior direito!' }
];

function initHelpSystem(): void {
  const saved = localStorage.getItem('avatar_id');
  if (saved && AVATAR_PROFILES[saved]) {
    setAvatar(saved);
  } else {
    // Primeira vez do usuário
    openOnboardingModal();
  }
}

function openOnboardingModal(): void {
  const modal = $('onboarding-modal');
  if (modal) {
    modal.style.display = 'flex';
    $('step-0-selection').style.display = 'flex';
    $('step-tour-text').style.display = 'none';
    $('btn-next-step').style.display = 'none';
    $('tour-step-title').innerText = 'Escolha seu Guia Virtual 🤖';
    currentTourStep = 0;
  }
}

function closeOnboardingModal(): void {
  const modal = $('onboarding-modal');
  if (modal) modal.style.display = 'none';
  if (!selectedAvatarId) {
    // Fallback padrão se fechar sem escolher
    setAvatar('maria_julia');
  }
}

function selectAvatar(id: string): void {
  setAvatar(id);
  
  // Transition to Tour
  $('step-0-selection').style.display = 'none';
  const textContainer = $('step-tour-text');
  textContainer.style.display = 'block';
  $('btn-next-step').style.display = 'inline-block';
  
  showTourStep();
}

function setAvatar(id: string): void {
  selectedAvatarId = id;
  localStorage.setItem('avatar_id', id);
  const widgetImg = $<HTMLImageElement>('avatar-widget-img');
  if (widgetImg) {
    widgetImg.src = AVATAR_PROFILES[id].img;
    widgetImg.alt = AVATAR_PROFILES[id].name;
  }
}

function showTourStep(): void {
  if (currentTourStep < TOUR_STEPS.length) {
    const step = TOUR_STEPS[currentTourStep];
    $('tour-step-title').innerText = step.title;
    let txt = step.text;
    if (currentTourStep === 0 && selectedAvatarId) {
      txt = AVATAR_PROFILES[selectedAvatarId].greetings + '<br><br>' + txt;
    }
    $('step-tour-text').innerHTML = txt;
  } else {
    closeOnboardingModal();
  }
}

function nextTourStep(): void {
  currentTourStep++;
  showTourStep();
}

function toggleSpeechBubble(): void {
  const bubble = $('avatar-speech');
  if (!bubble || !selectedAvatarId) return;
  
  if (bubble.style.display === 'none' || bubble.style.display === '') {
    const tip = AVATAR_PROFILES[selectedAvatarId].tips[currentTab] || 'Em que posso ajudar?';
    $('speech-text').innerText = tip;
    bubble.style.display = 'block';
    // Auto-hide após 8 segundos
    setTimeout(() => {
      bubble.style.display = 'none';
    }, 8000);
  } else {
    bubble.style.display = 'none';
  }
}

// Inicializa o Help System no load
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(initHelpSystem, 1000);
});

/* ==========================================================================
   PWA - Service Worker & Install Prompt
   ========================================================================== */

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(reg => {
      console.log('Service Worker registrado com sucesso:', reg.scope);
    }).catch(err => {
      console.error('Falha ao registrar o Service Worker:', err);
    });
  });
}

window.addEventListener('beforeinstallprompt', (e: Event) => {
  e.preventDefault();
  deferredPrompt = e as any;
  const installBtn = document.getElementById('pwa-install-btn');
  if (installBtn) {
    installBtn.style.display = 'flex';
    installBtn.addEventListener('click', async () => {
      installBtn.style.display = 'none';
      if (deferredPrompt) {
        deferredPrompt.prompt();
        const outcome = await deferredPrompt.userChoice;
        console.log(`Instalação PWA: ${outcome.outcome}`);
        deferredPrompt = null;
      }
    });
  }
});

window.addEventListener('appinstalled', () => {
  console.log('PWA instalado com sucesso!');
  const installBtn = document.getElementById('pwa-install-btn');
  if (installBtn) installBtn.style.display = 'none';
});
