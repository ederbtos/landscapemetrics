# 🏞️ Landscape Metrics Extractor

![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Roadmap](https://img.shields.io/badge/roadmap-ver_ROADMAP.md-blue.svg)

> **Progresso: ver [ROADMAP.md](ROADMAP.md) para o status real, fase a fase** — o backend/frontend abaixo estão em produção, mas nem tudo que já existiu (versão Streamlit anterior) foi portado:
> - **Backend REST API em Python (FastAPI)** (`backend/app/main.py`): Autenticação JWT com cookie HttpOnly, credenciais GEE criptografadas (Fernet), histórico multi-tenant, IBGE API e LGPD.
> - **Frontend Web App em TypeScript (`static/`, compilado de `frontend-src/`)**: Interface Glassmorphism Dark Mode com mapas Leaflet, gráficos Chart.js, PWA Mobile, acessibilidade VLibras/WCAG 2.2 AA e Avatares 3D (**Maria Júlia & Pedro**).
> - **Machine Learning & Analytics**:
>   - **Não Supervisionado**: K-Means & DBSCAN com projeção 2D PCA, Curva do Cotovelo e Silhouette Score. Predição por Cadeia de Markov: lógica preservada em `landscape_core.py`, mas **sem rota de API/UI própria ainda** — ver ROADMAP.md.
>   - **Supervisionado (Etapa 2)**: **Random Forest**, **XGBoost** e **LightGBM** com **Validação Cruzada Espacial (*Spatial K-Fold*)**, **AUC-ROC**, **F1-Score**, **Matriz de Confusão** e **Importância por Permutação (*Permutation Importance*)**.
> - **Isolamento por Usuário (Multi-Tenant)**: tabelas `user_settings`/`metric_results`/`user_credentials` com isolamento estrito por `user_email`, em SQLite (`data/app.db`) — sem suporte a PostgreSQL implementado no backend atual.



**Aplicativo Web para extração de métricas de paisagem de pontos de interesse a partir da base de dados do MapBiomas**

Desenvolvido por [Pedro Higuchi](https://twitter.com/pe_hi) | Contato: higuchip@gmail.com
Contribuições: 
            [Eder Silva] | Contato: eder.silva@unievangelica.edu.br
            [Jeferson Araujo] | Contato: jeferson.araujo@unievangelica.edu.br
---

## 📖 Descrição

O **Landscape Metrics Extractor** é uma aplicação web (backend FastAPI + frontend TypeScript) que permite extrair e analisar métricas de paisagem para pontos específicos no território brasileiro. A aplicação utiliza dados do MapBiomas através do Google Earth Engine e calcula métricas detalhadas usando a biblioteca PyLandStats.

Cada usuário faz login (por e-mail/senha ou, opcionalmente, com Google) e cadastra sua **própria** credencial de conta de serviço do Earth Engine — não há mais uma conta de serviço única compartilhada entre todos os usuários. Veja o estado detalhado do projeto e o que falta em [ROADMAP.md](ROADMAP.md).

### 🎯 Funcionalidades Principais

- **🔑 Login por e-mail/senha (+ Google opcional)**: acesso à ferramenta só depois de autenticado, com cadastro aberto por e-mail/senha e um botão extra "Entrar com Google" quando configurado
- **🔒 Credenciais por usuário**: cada usuário cadastra e usa sua própria conta de serviço do Earth Engine, guardada criptografada
- **📍 Seleção Interativa**: Interface com mapas para seleção de pontos de interesse
- **🏘️ Área de interesse por município (IBGE)**: alternativa ao ponto+buffer — escolha um estado e um município (via API do IBGE) e a análise usa o limite territorial oficial inteiro, com preview do polígono no mapa antes de calcular
- **🛰️ Dados MapBiomas**: acesso à collection mais recente disponível (com fallback automático para collections anteriores)
- **📤 GeoTIFF próprio (opcional)**: alternativa ao MapBiomas/Earth Engine — envie seu próprio raster de cobertura do solo (até 5GB, códigos de classe MapBiomas). Se você também enviar um ponto de interesse, o app recorta a área do buffer automaticamente; se enviar **só o raster**, calcula as métricas para a extensão **inteira** do arquivo
- **🧭 Reprojeção automática**: se o GeoTIFF enviado estiver em coordenadas geográficas (graus), o app reprojeta automaticamente (zona UTM do ponto, ou SIRGAS 2000/Brazil Polyconic no modo raster inteiro) — não precisa reprojetar manualmente antes de enviar. O raster convertido fica disponível para download
- **🧮 Cálculo sob demanda**: o processamento só roda quando você clica em "Calcular métricas", com cada etapa visível em tempo real e uma barra de progresso única (etapa + %) do início ao fim — não recalcula sozinho a cada interação com a página
- **✨ Métricas reveladas uma a uma**: cada métrica de paisagem aparece em sua própria seção conforme é calculada, com gráfico de barras interativo (por classe) + tabela, em vez de só uma tabela técnica ao final
- **🧬 Matriz socioecológica (SSE) & Clustering**: agrega todas as suas análises salvas numa matriz multivariada e permite agrupá-las com K-Means/DBSCAN, com projeção 2D via PCA
- **📊 Análise Robusta**: Cálculo de 12+ métricas de paisagem diferentes, por classe e de nível de paisagem
- **🗺️ Visualização**: Mapas interativos (Leaflet) e gráficos (Chart.js) das classes de uso do solo
- **📜 Governança LGPD**: exportação dos seus dados em JSON e eliminação de conta sob demanda (Art. 18)
- **🐳 Docker**: imagem e `docker-compose.yml` prontos para rodar sem instalar dependências localmente

> Recursos que existiram na versão anterior (Streamlit) e ainda não têm equivalente no frontend atual — comparação entre múltiplos GeoTIFFs com relatório HTML, predição de anos futuros via cadeia de Markov, exportação em CSV/XLSX, enriquecimento da matriz SSE com CSV externo/população do IBGE — ver a nota em "[📍 Onde encontrar seus resultados](#-onde-encontrar-seus-resultados)" e o ROADMAP.md.

---

## 🛠️ Tecnologias Utilizadas

### Principais Bibliotecas

Backend em Python (FastAPI) + frontend em TypeScript compilado (`tsc`, sem bundler — ver seção "Estrutura do Projeto" abaixo). Versões conforme [backend/requirements.txt](backend/requirements.txt)/[package.json](package.json) — mantenha esses arquivos como referência única, esta tabela pode ficar desatualizada:

| Biblioteca | Versão | Função |
|------------|--------|---------|
| `fastapi` + `uvicorn` | 0.115.6 / 0.34.0 | API HTTP do backend |
| `typescript` | ^5.7 | Tipagem/compilação do frontend (`frontend-src/` → `static/app.js`) |
| `geemap` | 0.30.0 | Integração Google Earth Engine |
| `pylandstats` | 3.1.0 | Cálculo de métricas de paisagem |
| `geopandas` | 0.14.3 | Processamento de dados geoespaciais |
| `earthengine-api` | 0.1.394 | API Google Earth Engine |
| `rasterio` | 1.4.4 | Leitura/recorte do GeoTIFF enviado pelo usuário (fonte de dados alternativa) |
| `PyJWT` | 2.10.1 | Sessão de login por e-mail/senha (JWT assinado + refresh token) |
| `bcrypt` | 4.2.1 | Hash de senha das contas por e-mail/senha |
| `Authlib` + `httpx` | 1.7.2 / 0.28.1 | OAuth do login com Google (opcional, `GET /api/auth/google/login`) |
| `cryptography` | 49.0.0 | Criptografia (Fernet) das credenciais salvas por usuário |
| `requests` | 2.34.2 | Chamadas à API do IBGE (localidades, malhas territoriais, população estimada) |
| `scipy` | 1.17.1 | Predição de anos futuros (potência fracionária da matriz de transição, cadeia de Markov — ver ROADMAP.md) |

### Fontes de Dados

- **MapBiomas**: dados de uso e cobertura da terra (tenta Collection 9 e recua para 8/7/6 conforme disponibilidade)
- **IBGE**: limites municipais (malhas territoriais) e população estimada (SIDRA), usados na área de interesse por município e na matriz socioecológica
- **Google Earth Engine**: Plataforma de processamento geoespacial

---

## 📋 Pré-requisitos

### 1. Conta Google Earth Engine (cada usuário)

- Cadastro em: <https://earthengine.google.com>
- Criação de uma conta de serviço com a Earth Engine API habilitada
- Download do arquivo JSON das credenciais dessa conta de serviço

### 2. Credenciais OAuth do Google (opcional — só se quiser o botão "Entrar com Google")

- O login por e-mail/senha funciona sem nenhuma credencial externa — pule esta etapa se não quiser o botão do Google.
- Se quiser, crie em [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials), tipo "OAuth client ID" / "Web application" — cadastre `http://localhost:8000/api/auth/google/callback` (ou o domínio real em produção) em "Authorized redirect URIs"
- Preenche `google_client_id`/`google_client_secret`/`google_redirect_uri` (opcionais) em `backend/.env` — veja `backend/.env.example`

### 3. Python 3.11+

```bash
python --version  # Recomendado 3.11+ (imagem Docker usa python:3.11-slim)
```

---

## 🔧 Instalação

### 1. Clone o Repositório

```bash
git clone https://github.com/ederbtos/landscapemetrics.git
cd landscapemetrics
```

### 2. Configure os Segredos

```bash
cp backend/.env.example backend/.env
```

Edite `backend/.env` e preencha:

- `jwt_secret_key` (obrigatório): gere com `python -c "import secrets; print(secrets.token_hex(32))"` — assina o JWT de sessão
- `app_encryption_key` (obrigatório): gere com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `cors_origins` (obrigatório): origens autorizadas a chamar a API (em produção, o domínio real em HTTPS)
- `google_client_id`/`google_client_secret`/`google_redirect_uri` (opcional): só se quiser o botão "Entrar com Google"

Essas configurações protegem o login e a criptografia das credenciais do Earth Engine — **nunca** faça commit desse arquivo (já está no `.gitignore`).

### 3a. Rodar com Docker (recomendado)

```bash
docker compose up --build
```

### 3b. Rodar localmente sem Docker

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r backend/requirements.txt

npm install
npm run build          # compila frontend-src/ -> static/app.js
# npm run watch para recompilar automaticamente ao editar os .ts

cd backend && uvicorn app.main:app --reload
```

Acesse `http://localhost:8000`.

### 4. Deploy em produção (HTTPS)

Fase 4 do roadmap: a stack de produção (HTTPS automático via [Caddy](https://caddyserver.com/) + Let's Encrypt, genérica para qualquer VPS com Docker) sobe com um único comando, rodado **no servidor**:

```bash
# no servidor, com o domínio já apontando (DNS tipo A) para o IP dele
# e backend/.env já preenchido (jwt_secret_key, app_encryption_key,
# cors_origins e opcionalmente google_client_id/secret/redirect_uri)
./scripts/deploy.sh seu-dominio.exemplo.com
```

O script gera o `Caddyfile` a partir de `Caddyfile.example` e sobe `docker-compose.prod.yml` (app + Caddy) — o `Dockerfile` compila o frontend TypeScript automaticamente num estágio Node separado antes de montar a imagem final. Se estiver usando o login com Google, ajuste `google_redirect_uri` em `backend/.env` e a credencial OAuth no Google Cloud Console para `https://SEU_DOMINIO/api/auth/google/callback`. Se preferir uma plataforma gerenciada (Railway, Render) que já resolve HTTPS por conta própria, `docker-compose.prod.yml`/Caddy/`deploy.sh` não são necessários — use direto o `Dockerfile`.

Para backup de `data/app.db` (credenciais criptografadas por usuário), agende `./scripts/backup-db.sh` via `cron` — veja o cabeçalho do script para o exemplo de crontab e a variável opcional `BACKUP_REMOTE`.

Detalhes e decisões pendentes (qual servidor/domínio usar) em [ROADMAP.md](ROADMAP.md#fase-4--deploy).

---

## 🎮 Como Usar

### 1. Faça Login

Abra o app e crie uma conta no botão "Entrar / Cadastrar" (e-mail + senha) —
ou, se o botão "Entrar com Google" estiver disponível, use sua conta Google.
Depois de logado, cadastre sua credencial do Earth Engine na aba "📍 Análise
de Paisagem" (seção "🔑 Cadastrar/atualizar credencial do Earth Engine") — só
é obrigatória se você for usar a fonte MapBiomas; fica salva criptografada
para as próximas sessões.

A sessão sobrevive a um F5 (refresh token em cookie httpOnly, renovado
automaticamente via `POST /api/auth/refresh`) — só precisa logar de novo
depois de ~30 dias sem acessar, ou depois de "Sair".

### 2. Aba "📍 Análise de Paisagem"

**Passo 1 — Área de interesse**: escolha entre

- **📌 Ponto + Buffer**: clique no mapa para marcar o ponto e ajuste o raio do buffer (500-20.000m) no slider
- **🏘️ Limite Municipal (IBGE)**: escolha um estado e um município nos dois seletores — a área de interesse vira o limite territorial oficial do município inteiro

**Passo 2 — Fonte de dados**: escolha entre

- **MapBiomas (Google Earth Engine)**: usa a collection mais recente disponível (ver [🌍 Classes MapBiomas Suportadas](#-classes-mapbiomas-suportadas)) — exige a credencial do Earth Engine já cadastrada
- **Meu Raster (GeoTIFF Próprio)**: envie um único raster de cobertura do solo, mesmos códigos de classe do MapBiomas. Se estiver em coordenadas geográficas (graus), é reprojetado automaticamente antes de calcular

**Passo 3 — Calcular**: o botão "🧮 Calcular Métricas da Paisagem" só libera quando os passos 1 e 2 estiverem completos. Os resultados aparecem ao lado: resumo de nível de paisagem (SHDI/densidade de manchas/densidade de borda), gráfico de barras por classe (Chart.js) e a tabela de métricas por classe.

### 3. Aba "🧬 Matriz Socioecológica & Clustering"

Assim que você tiver ao menos uma análise salva, clique em "🔄 Atualizar
Matriz" para ver todas as suas análises agregadas numa tabela. Abaixo,
escolha K-Means (define quantos clusters, K) ou DBSCAN (define raio de
vizinhança e mínimo de amostras) e clique em "⚡ Executar Agrupamento ML" —
mostra os perfis de cada cluster e uma projeção 2D via PCA.

### 4. Aba "📜 Privacidade & LGPD"

- **Exportar meus Dados**: baixa um JSON com seu histórico e credenciais cadastradas (Art. 18, V)
- **Eliminação de Conta**: apaga permanentemente conta, credenciais, preferências e histórico salvo (Art. 18, VI) — ação irreversível, pede confirmação

> ⚠️ Se a extração de dados reais do MapBiomas/Earth Engine falhar (ex.: buffer
> muito pequeno ou região sem cobertura no asset), o processamento é
> interrompido com uma mensagem de erro — o app nunca substitui por dados de
> exemplo. Aumente o raio do buffer, selecione outro ponto/município e tente
> de novo.

---

## 📍 Onde encontrar seus resultados

Resumo de cada resultado calculado e onde ele aparece na tela do frontend atual (`static/`, aba única com navegação lateral — ver seção "Estrutura do Projeto" abaixo).

| Resultado | Onde aparece na tela | Como exportar |
|---|---|---|
| Resumo de métricas de nível de paisagem (SHDI, densidade de manchas, densidade de borda) | Aba "📍 Análise de Paisagem", acima do gráfico, após clicar em "Calcular Métricas" | — (visual; sem export próprio ainda) |
| Tabela + gráfico de métricas por classe | Mesma aba, ao lado do passo a passo | — (visual; sem export próprio ainda) |
| Matriz socioecológica (SSE): todas as suas análises salvas agregadas | Aba "🧬 Matriz Socioecológica & Clustering" | — (visual; sem export próprio ainda) |
| Agrupamento K-Means/DBSCAN (perfis + projeção PCA 2D) | Mesma aba, abaixo da matriz SSE | — (visual; sem export próprio ainda) |
| Exportação de dados pessoais (Art. 18 LGPD) | Aba "📜 Privacidade & LGPD" | Botão **"Baixar Dados em JSON"** |

> **Atenção — funcionalidades documentadas no histórico do projeto mas ainda sem equivalente no frontend atual** (ver [ROADMAP.md](ROADMAP.md) para o detalhamento): comparação entre múltiplos GeoTIFFs, relatório HTML para impressão/PDF, predição de anos futuros via cadeia de Markov, métricas por município em lote via shapefile, e exportação em CSV/XLSX de qualquer resultado. Essas features existiam na versão anterior (Streamlit) e foram descobertas sem porte durante a migração para o backend FastAPI + frontend TypeScript — a lógica de alguma delas (predição de Markov) já foi preservada em `backend/app/services/landscape_core.py`, mas nenhuma tem rota de API nem UI própria hoje.

---

## 📊 Métricas Calculadas

Organizadas conforme as categorias do [FRAGSTATS](https://fragstats.org/index.php/background/landscape-metrics) — ver o expander "📊 Detalhamento das métricas" no rodapé do app para a lista completa e o que fica de fora (e por quê).

### Por classe (uma linha por classe de cobertura do solo)

| Métrica | Descrição | Unidade |
|---------|-----------|---------|
| `total_area` | Área total da classe | ha |
| `proportion_of_landscape` | Proporção na paisagem | % |
| `number_of_patches` | Número de manchas | - |
| `patch_density` | Densidade de manchas | manchas/100ha |
| `largest_patch_index` | Índice da maior mancha | % |
| `total_edge` | Total de bordas | m |
| `edge_density` | Densidade de borda | m/ha |
| `landscape_shape_index` | Índice de forma da paisagem | - |
| `area_mn` | Área média das manchas | ha |
| `perimeter_mn` | Perímetro médio | m |
| `shape_index_mn` | Índice de forma médio | - |
| `fractal_dimension_mn` | Dimensão fractal média | - |
| `euclidean_nearest_neighbor_mn` | Distância média ao vizinho mais próximo | m |
| `total_core_area` | Área central total (Core Area) | ha |
| `core_area_proportion_of_landscape` | Proporção de área central na paisagem | % |
| `core_area_mn` | Área central média por mancha | ha |
| `core_area_index_mn` | Índice médio de área central | % |
| `number_of_disjunct_core_areas` | Número de áreas centrais disjuntas | - |
| `disjunct_core_area_mn` | Área central disjunta média | ha |

### Nível de paisagem (um único valor global, exibido como cards no app)

| Métrica | Descrição |
|---------|-----------|
| SHDI | Índice de Diversidade de Shannon |
| SHEI | Uniformidade de Shannon |
| SIDI | Índice de Diversidade de Simpson |
| SIEI | Uniformidade de Simpson |
| PR | Riqueza de Manchas (nº de classes presentes) |
| CONTAG | Contágio |
| MESH | Tamanho Efetivo de Malha |
| PD | Densidade de Manchas (nível de paisagem) |
| ED | Densidade de Borda (nível de paisagem) |
| LSI | Índice de Forma da Paisagem (nível de paisagem) |

> **Fora do escopo por ora**: Aggregation Index (AI), Clumpiness Index (CLUMPY), Landscape Division Index (DIVISION) e Splitting Index (SPLIT) não têm método equivalente na versão do PyLandStats usada neste projeto. Interspersion & Juxtaposition Index (IJI), Proximity Index e Contiguity Index existem como métodos na biblioteca mas não estão implementados nela (retornam erro). Métricas de Contraste (ex.: TECI) exigiriam uma matriz de similaridade entre classes configurada pelo usuário, não suportada pela interface atual.

---

## 🗂️ Estrutura do Projeto

```
landscapemetrics/
├── backend/                        # API FastAPI — único backend do projeto
│   ├── app/
│   │   ├── main.py                 # Monta rotas + serve o frontend estático em "/"
│   │   ├── api/routes/             # Auth, credenciais, métricas, IBGE, SSE, PRODES, MapBiomas, ANA...
│   │   ├── core/config.py          # Settings via variáveis de ambiente (.env)
│   │   ├── db/                     # Schema + acesso a data/app.db (SQLite)
│   │   └── services/               # landscape_core.py, clustering.py, supervised_models.py (lógica pura)
│   ├── requirements.txt            # Dependências Python do backend
│   ├── .env.example                # Modelo de configuração de segredos
│   └── .env                        # Segredos locais (nunca commitado)
├── frontend-src/                   # Fonte TypeScript do frontend (compila para static/app.js)
│   ├── app.ts
│   └── globals.d.ts
├── static/                         # Frontend servido pelo backend (landing page + ferramenta + PWA)
│   └── app.js                      # Gerado por `npm run build` — nunca editado à mão
├── package.json, tsconfig.json     # Build do frontend (tsc, sem bundler)
├── Dockerfile                      # Imagem da aplicação (compila o frontend + empacota backend/static)
├── docker-compose.yml              # Orquestração local (app na porta 8000)
├── docker-compose.prod.yml         # Stack de produção (app + Caddy/HTTPS)
├── Caddyfile.example               # Modelo de config do proxy reverso (produção)
├── scripts/
│   ├── deploy.sh                   # Deploy de produção em 1 comando (Fase 4)
│   ├── backup-db.sh                # Backup datado de data/app.db (+ envio remoto opcional)
│   └── seed_*.py                   # Pré-carga dos dados de referência nacionais (Fase 10)
├── README.md                       # Este arquivo
├── ROADMAP.md                      # Status do projeto e próximas fases
└── data/
    └── app.db                      # SQLite com usuários/credenciais/histórico (gerado em runtime)
```

---

## 🔒 Segurança

### Validações Implementadas

- ✅ **Login obrigatório**: acesso à ferramenta só após autenticação (e-mail/senha com hash bcrypt + JWT, ou Google OAuth quando configurado)
- ✅ **Credenciais isoladas por usuário**: cada usuário só acessa a própria conta de serviço do Earth Engine, cifrada em repouso (Fernet) em `data/app.db`
- ✅ **Tamanho de arquivo**: Máximo 10MB (ponto) / 5GB (GeoTIFF)
- ✅ **Tipos permitidos**: `.geojson` ou shapefile compactado em `.zip` para o ponto; `.tif`/`.tiff` para o raster próprio
- ✅ **Sanitização**: Nomes de arquivo e caminhos
- ✅ **Path traversal**: Proteção contra ataques
- ✅ **Sem dados fictícios**: se a extração real do MapBiomas/Earth Engine falhar, o processamento é interrompido em vez de gerar métricas a partir de dados de exemplo

### Limites de Uso

- **Pontos por upload**: 1 ponto
- **Buffer**: 1.000-10.000m
- **Região**: Apenas território brasileiro (cobertura MapBiomas)

---

## 🌍 Classes MapBiomas Suportadas

| Código | Classe | Código | Classe |
|--------|--------|--------|--------|
| 1 | Floresta | 15 | Pastagem |
| 4 | Savana | 18 | Agricultura |
| 12 | Campo | 21 | Mosaico Agro-Pastagem |
| 26 | Água | 24 | Área Urbanizada |

*Classificação completa disponível em: [MapBiomas](https://mapbiomas.org/codigos-da-legenda)*

---

## 🐛 Solução de Problemas

### Problemas Comuns

#### 1. Erro de Autenticação Earth Engine

```text
❌ Falha na inicialização do Earth Engine
```

**Solução**: confira se o JSON colado é o da própria conta de serviço (campos `client_email`, `private_key`, `project_id`), se a Earth Engine API está habilitada nesse projeto GCP e se a conta de serviço tem permissão de acesso ao Earth Engine. Você pode corrigir e reenviar o JSON no expander "🔑 Atualizar credenciais do Earth Engine".

#### 2. Arquivo GeoJSON Inválido

```text
❌ Nenhuma geometria válida encontrada
```

**Solução**: Certifique-se de que o arquivo contém exatamente um ponto válido.

#### 3. "Não foi possível extrair dados reais do MapBiomas"

```text
❌ Não foi possível extrair dados reais do MapBiomas para esta área.
```

**Solução**: a extração de pixels reais falhou e o app não gera uma análise substituta — expanda o expander de detalhes do erro para a causa exata. Causas comuns: buffer muito pequeno para a resolução do raster (30m), ponto numa região sem cobertura no asset MapBiomas testado, ou instabilidade temporária do Earth Engine. Tente novamente, aumente o raio do buffer ou selecione outro ponto.

#### 4. Erros ao usar "Meu raster (GeoTIFF)"

> Se o seu GeoTIFF estiver em coordenadas geográficas (graus), o app reprojeta automaticamente — você não precisa mais reprojetar manualmente antes de enviar nem verá um erro só por causa disso.

```text
❌ A área do buffer não intersecta o raster enviado.
```

**Solução**: confirme que o ponto selecionado está dentro da área coberta pelo raster, ou aumente o buffer. (Esse erro só ocorre com ponto enviado — no modo raster inteiro, sem ponto, ele não se aplica.)

```text
❌ Nenhum pixel válido encontrado no raster enviado — o arquivo parece conter apenas valores nodata.
```

**Solução**: erro do modo raster inteiro (GeoTIFF enviado sem ponto de interesse) — confirme que o arquivo realmente contém dados de classificação e não só nodata.

### Logs e Debug

Rodando localmente sem Docker (`cd backend && ../.venv/Scripts/uvicorn app.main:app --reload`), os logs aparecem no próprio terminal. Para mais detalhe, ajuste o nível de log do Python (ex.: `logging.basicConfig(level=logging.DEBUG)`) ou rode com `uvicorn ... --log-level debug`. Via Docker: `docker compose logs -f app`.

---

## 🤝 Contribuindo

### Como Contribuir

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -am 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Abra um Pull Request

### Diretrizes

- Siga o padrão PEP 8 para Python
- Adicione testes para novas funcionalidades
- Atualize a documentação (README/ROADMAP) quando necessário
- Mantenha compatibilidade com Python 3.11+

---

## 📄 Licença

Este projeto está licenciado sob a Licença MIT - veja o arquivo [LICENSE](LICENSE) para detalhes.

---

## 📚 Referências

### Artigos Científicos

- **Bosch M.** (2019). PyLandStats: An open-source Pythonic library to compute landscape metrics. *PLOS ONE*, 14(12), 1-19.
- **Souza et al.** (2020). Reconstructing Three Decades of Land Use and Land Cover Changes in Brazilian Biomes with Landsat Archive and Earth Engine. *Remote Sensing*, 12(17).

### Ferramentas e Dados

- [MapBiomas](https://mapbiomas.org/) - Mapeamento anual da cobertura e uso da terra do Brasil
- [Google Earth Engine](https://earthengine.google.com/) - Plataforma de análise geoespacial
- [PyLandStats](https://pylandstats.readthedocs.io/) - Biblioteca para métricas de paisagem
- [FastAPI](https://fastapi.tiangolo.com/) - Framework do backend
- [TypeScript](https://www.typescriptlang.org/) - Tipagem do frontend

---

## 👨‍💻 Autor

**Pedro Higuchi** (autor original)

- Twitter: [@pe_hi](https://twitter.com/pe_hi)
- Email: higuchip@gmail.com

Este repositório é um fork mantido em [github.com/ederbtos/landscapemetrics](https://github.com/ederbtos/landscapemetrics), com as mudanças de login, credenciais por usuário e Docker descritas em [ROADMAP.md](ROADMAP.md).

---

## 🆘 Suporte

Para suporte, abra uma [issue](https://github.com/ederbtos/landscapemetrics/issues) ou entre em contato via email.

### Links Úteis

- [Documentação FastAPI](https://fastapi.tiangolo.com/)
- [Google Earth Engine Docs](https://developers.google.com/earth-engine/)
- [PyLandStats Docs](https://pylandstats.readthedocs.io/)
- [MapBiomas Docs](https://mapbiomas.org/downloads)

---

**⭐ Se este projeto foi útil, considere dar uma estrela no GitHub!**
