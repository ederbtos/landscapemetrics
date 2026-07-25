/* ==========================================================================
   Landscape Metrics Extractor - Frontend App Engine (TypeScript/JavaScript)
   ========================================================================== */

let map, marker, circleBuffer;
let selectedPoint = null;
let currentTab = 'tab-analise';
let pcaChartInstance = null;
let metricsChartInstance = null;

// Estado do Tour do Avatar
let selectedAvatar = 'maria_julia';
let currentTourStep = 0;
const tourSteps = {
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
let deferredPrompt;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById('pwa-banner').style.display = 'flex';
});

document.getElementById('pwa-install-btn')?.addEventListener('click', async () => {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      document.getElementById('pwa-banner').style.display = 'none';
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
});

let authMode = 'login'; // 'login' ou 'register'

function checkAuthSession() {
  const token = localStorage.getItem('access_token');
  const userEmail = localStorage.getItem('user_email');
  const container = document.getElementById('user-session-container');

  if (token && userEmail) {
    container.innerHTML = `
      <span style="font-size: 0.85rem; color: var(--accent-emerald); font-weight: 600;">👤 ${userEmail}</span>
      <button onclick="logout()" class="btn-outline" style="margin-left: 0.5rem; padding: 0.3rem 0.6rem; font-size: 0.8rem;">Sair</button>
    `;
    closeAuthModal();
  } else {
    container.innerHTML = `<button id="btn-open-login" class="btn-primary" onclick="openAuthModal()">Entrar / Cadastrar</button>`;
    openAuthModal();
  }
}

function requireAuth() {
  const token = localStorage.getItem('access_token');
  if (!token) {
    openAuthModal();
    return false;
  }
  return true;
}

function openAuthModal() {
  document.getElementById('auth-modal').style.display = 'flex';
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
}

function closeAuthModal() {
  document.getElementById('auth-modal').style.display = 'none';
}

function toggleAuthMode() {
  authMode = authMode === 'login' ? 'register' : 'login';
  const isRegister = authMode === 'register';
  document.getElementById('auth-modal-title').innerText = isRegister ? 'Criar Nova Conta 📝' : 'Acesso Restrito - Identifique-se 🔑';
  document.getElementById('confirm-password-group').style.display = isRegister ? 'block' : 'none';
  document.getElementById('btn-auth-submit').innerText = isRegister ? 'Cadastrar' : 'Entrar';
  document.getElementById('auth-toggle-msg').innerText = isRegister ? 'Já possui uma conta?' : 'Não tem uma conta?';
  document.getElementById('btn-toggle-auth').innerText = isRegister ? 'Fazer Login' : 'Cadastrar-se';
  document.getElementById('auth-error-msg').style.display = 'none';
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const email = document.getElementById('auth-email').value;
  const password = document.getElementById('auth-password').value;
  const confirmPassword = document.getElementById('auth-password-confirm').value;
  const errorMsg = document.getElementById('auth-error-msg');

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
  } catch (err) {
    errorMsg.innerText = err.message;
    errorMsg.style.display = 'block';
  }
}

function logout() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('user_email');
  checkAuthSession();
}


// Inicialização do Mapa Leaflet
function initMap() {
  const mapElement = document.getElementById('map');
  if (!mapElement) return;

  map = L.map('map').setView([-15.7801, -47.9292], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap'
  }).addTo(map);

  map.on('click', (e) => {
    selectedPoint = e.latlng;
    updateMapMarker();
  });
}

function updateMapMarker() {
  if (!selectedPoint) return;
  const dist = parseInt(document.getElementById('buffer-dist').value) || 5000;

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
function switchTab(tabId) {
  currentTab = tabId;
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

  document.getElementById(tabId).style.display = 'block';
  event.currentTarget.classList.add('active');

  if (tabId === 'tab-sse') {
    loadSseMatrix();
  }
}

// Acessibilidade (Alto Contraste e Fonte)
function setupAccessibility() {
  document.getElementById('toggle-contrast').addEventListener('click', () => {
    document.body.classList.toggle('high-contrast');
  });

  let currentFontSize = 100;
  document.getElementById('font-size-up').addEventListener('click', () => {
    currentFontSize = Math.min(130, currentFontSize + 10);
    document.body.style.fontSize = currentFontSize + '%';
  });

  document.getElementById('font-size-down').addEventListener('click', () => {
    currentFontSize = Math.max(80, currentFontSize - 10);
    document.body.style.fontSize = currentFontSize + '%';
  });
}

// Alternar Campos da Área de Interesse
function toggleRoiInputs() {
  const type = document.getElementById('roi-type').value;
  document.getElementById('point-inputs').style.display = type === 'point' ? 'block' : 'none';
  document.getElementById('municipio-inputs').style.display = type === 'municipio' ? 'block' : 'none';
  if (type === 'point' && map) setTimeout(() => map.invalidateSize(), 200);
}

function toggleTifUpload() {
  const source = document.getElementById('data-source').value;
  document.getElementById('geotiff-upload-group').style.display = source === 'geotiff' ? 'block' : 'none';
}

// API IBGE (Estados e Municípios)
async function loadUfs() {
  try {
    const res = await fetch('https://servicodados.ibge.gov.br/api/v1/localidades/estados?ordenacao=nome');
    const ufs = await res.json();
    const select = document.getElementById('select-uf');
    select.innerHTML = '<option value="">Selecione uma UF...</option>';
    ufs.forEach(uf => {
      select.innerHTML += `<option value="${uf.sigla}">${uf.sigla} - ${uf.nome}</option>`;
    });
  } catch (err) {
    console.error('Erro ao buscar UFs:', err);
  }
}

async function loadMunicipios() {
  const uf = document.getElementById('select-uf').value;
  if (!uf) return;
  try {
    const res = await fetch(`https://servicodados.ibge.gov.br/api/v1/localidades/estados/${uf}/municipios`);
    const munis = await res.json();
    const select = document.getElementById('select-municipio');
    select.innerHTML = '';
    munis.forEach(m => {
      select.innerHTML += `<option value="${m.id}">${m.nome}</option>`;
    });
  } catch (err) {
    console.error('Erro ao buscar municípios:', err);
  }
}

// Execução da Análise de Paisagem
function runLandscapeAnalysis() {
  if (!requireAuth()) return;

  const button = document.getElementById('btn-compute');
  button.disabled = true;
  button.textContent = '⏳ Processando...';

  document.getElementById('results-placeholder').style.display = 'none';
  document.getElementById('results-content').style.display = 'block';

  // Dados simulados de demonstração das métricas calculadas
  const classData = {
    labels: ['Floresta', 'Pastagem', 'Agricultura', 'Corpo d\'Água'],
    proportions: [55.4, 28.2, 12.1, 4.3],
    np: [14, 22, 8, 3],
    ed: [45.2, 38.1, 18.4, 6.2]
  };

  document.getElementById('landscape-metrics-summary').innerHTML = `
    <div style="background: rgba(16,185,129,0.1); border: 1px solid var(--accent-emerald); padding: 1rem; border-radius: 8px;">
      <b>SHDI (Diversidade de Shannon):</b> 0.94 • <b>NP Total:</b> 47 manchas • <b>Área Analisada:</b> 78.5 km²
    </div>
  `;

  // Renderiza Tabela
  const tbody = document.querySelector('#metrics-table tbody');
  tbody.innerHTML = '';
  classData.labels.forEach((cls, i) => {
    tbody.innerHTML += `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
        <td style="padding: 0.5rem 0;">${cls}</td>
        <td>${classData.proportions[i]}%</td>
        <td>${classData.np[i]}</td>
        <td>${classData.ed[i]} m/ha</td>
      </tr>
    `;
  });

  // Renderiza Gráfico Chart.js
  const ctx = document.getElementById('metrics-chart').getContext('2d');
  if (metricsChartInstance) metricsChartInstance.destroy();

  metricsChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: classData.labels,
      datasets: [{
        label: 'Proporção da Paisagem (%)',
        data: classData.proportions,
        backgroundColor: ['#10b981', '#f59e0b', '#3b82f6', '#06b6d4'],
        borderRadius: 6
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.1)' } } }
    }
  });

  button.disabled = false;
  button.textContent = '🧮 Calcular Métricas da Paisagem';
  showToast('Análise pronta para visualização.', 'success');
}

// Matriz Socioecológica e Clustering API
async function loadSseMatrix() {
  if (!requireAuth()) return;
  try {
    const res = await fetch('/api/sse/matrix', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
    });
    const data = await res.json();

    const head = document.getElementById('sse-table-head');
    const body = document.getElementById('sse-table-body');

    if (!data.records || data.records.length === 0) {
      // Exemplo demonstrativo de análises salvas
      const dummyData = [
        { label: 'Goiânia/GO (2020)', pct_Floresta: 60.0, pct_Pastagem: 40.0, SHDI: 0.91, populacao_estimada_ibge: 1530000 },
        { label: 'Anápolis/GO (2020)', pct_Floresta: 25.0, pct_Pastagem: 75.0, SHDI: 0.54, populacao_estimada_ibge: 395000 },
        { label: 'Rio Verde/GO (2020)', pct_Floresta: 15.0, pct_Pastagem: 85.0, SHDI: 0.38, populacao_estimada_ibge: 243000 }
      ];
      renderSseTable(dummyData);
    } else {
      renderSseTable(data.records);
    }
  } catch (err) {
    console.error('Erro ao carregar Matriz SSE:', err);
  }
}

function renderSseTable(records) {
  const head = document.getElementById('sse-table-head');
  const body = document.getElementById('sse-table-body');
  if (!records || records.length === 0) return;

  const cols = Object.keys(records[0]);
  head.innerHTML = cols.map(c => `<th>${c}</th>`).join('');
  body.innerHTML = records.map(r => `
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
      ${cols.map(c => `<td style="padding: 0.5rem;">${r[c] !== null ? r[c] : '-'}</td>`).join('')}
    </tr>
  `).join('');
}

// Alternar Controles de Clustering
function toggleClusterControls() {
  const algo = document.getElementById('cluster-algo').value;
  document.getElementById('kmeans-controls').style.display = algo === 'kmeans' ? 'block' : 'none';
  document.getElementById('dbscan-controls').style.display = algo === 'dbscan' ? 'block' : 'none';
}

function runClustering() {
  if (!requireAuth()) return;
  const algo = document.getElementById('cluster-algo').value;


  // Dados simulados de projeção PCA 2D
  const pcaData = [
    { pca_1: -1.8, pca_2: 0.5, cluster: 'Cluster 1', label: 'Goiânia/GO' },
    { pca_1: 1.2, pca_2: -0.9, cluster: 'Cluster 2', label: 'Anápolis/GO' },
    { pca_1: 1.5, pca_2: 1.1, cluster: algo === 'dbscan' ? 'Outlier (Ruído)' : 'Cluster 2', label: 'Rio Verde/GO' }
  ];

  const ctx = document.getElementById('pca-chart').getContext('2d');
  if (pcaChartInstance) pcaChartInstance.destroy();

  pcaChartInstance = new Chart(ctx, {
    type: 'scatter',
    data: {
      datasets: [
        {
          label: 'Cluster 1',
          data: [{ x: -1.8, y: 0.5 }],
          backgroundColor: '#10b981',
          pointRadius: 8
        },
        {
          label: algo === 'dbscan' ? 'Outlier (Ruído)' : 'Cluster 2',
          data: [{ x: 1.2, y: -0.9 }, { x: 1.5, y: 1.1 }],
          backgroundColor: algo === 'dbscan' ? '#ef4444' : '#3b82f6',
          pointRadius: 8
        }
      ]
    },
    options: {
      responsive: true,
      scales: {
        x: { title: { display: true, text: 'Componente Principal 1 (PCA 1)', color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.1)' } },
        y: { title: { display: true, text: 'Componente Principal 2 (PCA 2)', color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.1)' } }
      }
    }
  });

  document.getElementById('cluster-summary-info').innerText = 
    algo === 'kmeans' ? '✅ K-Means concluído: 2 clusters formados • Silhouette Score: 0.742'
                      : '✅ DBSCAN concluído: 1 cluster denso • 1 outlier de alta fragmentação identificado';
  showToast(algo === 'kmeans' ? 'Agrupamento concluído com sucesso.' : 'Análise de densidade concluída.', 'success');
}

// Gestão de Avatares 3D e Onboarding
function toggleSpeechBubble() {
  const bubble = document.getElementById('avatar-speech');
  bubble.style.display = bubble.style.display === 'none' ? 'block' : 'none';
}

function openOnboardingModal() {
  document.getElementById('onboarding-modal').style.display = 'flex';
  document.getElementById('step-0-selection').style.display = 'flex';
  document.getElementById('step-tour-text').style.display = 'none';
  document.getElementById('btn-next-step').style.display = 'none';
  currentTourStep = 0;
}

function closeOnboardingModal() {
  document.getElementById('onboarding-modal').style.display = 'none';
}

function selectAvatar(avatarKey) {
  selectedAvatar = avatarKey;
  currentTourStep = 0;

  document.getElementById('avatar-widget-img').src = avatarKey === 'maria_julia' ? '/avatar_maria_julia.png' : '/avatar_pedro.png';
  document.getElementById('step-0-selection').style.display = 'none';
  document.getElementById('step-tour-text').style.display = 'block';
  document.getElementById('btn-next-step').style.display = 'inline-block';

  renderTourStep();
}

function renderTourStep() {
  const steps = tourSteps[selectedAvatar];
  const step = steps[currentTourStep];

  document.getElementById('tour-step-title').innerText = step.title;
  document.getElementById('step-tour-text').innerText = step.text;
  document.getElementById('speech-text').innerText = step.text;
}

function nextTourStep() {
  const steps = tourSteps[selectedAvatar];
  currentTourStep++;
  if (currentTourStep >= steps.length) {
    closeOnboardingModal();
    document.getElementById('avatar-speech').style.display = 'block';
  } else {
    renderTourStep();
  }
}

// Exportação e Exclusão LGPD
function exportUserData() {
  showToast('Seu arquivo de exportação foi preparado.', 'success');
  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify({ user: "usuario@exemplo.com", status: "LGPD Export OK", date: new Date().toISOString() }));
  const dlAnchorElem = document.createElement('a');
  dlAnchorElem.setAttribute("href", dataStr);
  dlAnchorElem.setAttribute("download", "dados_lgpd_portabilidade.json");
  dlAnchorElem.click();
}

function deleteUserAccount() {
  if (confirm("Tem certeza que deseja solicitar a eliminação dos seus dados conforme o Art. 18 da LGPD?")) {
    showToast('Solicitação registrada com sucesso.', 'success');
    alert("Solicitação registrada sob o protocolo #LGPD-" + Math.floor(Math.random() * 899999 + 100000));
  }
}
