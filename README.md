# 🏞️ Landscape Metrics Extractor

![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Progresso](https://img.shields.io/badge/roadmap-96%25-yellow.svg)

> ℹ️ O link de demo online desta versão foi removido: a arquitetura de login e
> credenciais por usuário mudou (veja [ROADMAP.md](ROADMAP.md)) e a Fase 4
> (deploy público com HTTPS) ainda está pendente de execução. Por enquanto,
> rode localmente ou via Docker — veja [🔧 Instalação](#-instalação).
>
> **Progresso: 96%** — Fases 1-3 (landing page, login, credenciais por
> usuário), Fase 5 (motor de métricas de paisagem: MapBiomas + GeoTIFF
> próprio, um ou vários arquivos, reprojeção automática, métricas de
> classe + paisagem do FRAGSTATS) e Fase 6 (área municipal via IBGE, matriz
> socioecológica e predição de anos futuros via Markov) concluídas; Fase 4
> (deploy) está totalmente automatizada em
> [scripts/deploy.sh](scripts/deploy.sh), faltando só a decisão de
> servidor/domínio e a execução. Detalhamento por fase em
> [ROADMAP.md](ROADMAP.md#progresso-geral-96).

**Aplicativo Web para extração de métricas de paisagem de pontos de interesse a partir da base de dados do MapBiomas**

Desenvolvido por [Pedro Higuchi](https://twitter.com/pe_hi) | Contato: higuchip@gmail.com
Contribuições: 
            [Eder Silva] | Contato: eder.silva@unievangelica.edu.br
            [Jeferson Araujo] | Contato: jeferson.araujo@unievangelica.edu.br
---

## 📖 Descrição

O **Landscape Metrics Extractor** é uma aplicação web desenvolvida em Streamlit que permite extrair e analisar métricas de paisagem para pontos específicos no território brasileiro. A aplicação utiliza dados do MapBiomas através do Google Earth Engine e calcula métricas detalhadas usando a biblioteca PyLandStats.

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
- **📚 Múltiplos GeoTIFFs comparados**: envie mais de um raster próprio (ex.: anos diferentes da mesma área) — cada um é processado separadamente e comparado num gráfico por métrica (ano identificado pelo nome do arquivo, quando presente), com um relatório HTML para baixar, abrir no navegador e imprimir/salvar como PDF
- **🔮 Predição para anos futuros (Markov)**: com 2+ GeoTIFFs de anos diferentes, o app monta a matriz de transição entre classes de uso do solo e projeta a proporção futura de cada classe para os anos que você escolher — método não-espacial, projeta só proporções agregadas, não um mapa futuro
- **🧬 Matriz socioecológica (SSE)**: agrega todas as suas análises salvas (ponto ou município, ao longo do tempo) numa matriz multivariada — métricas de paisagem por linha, com a opção de anexar variáveis socioeconômicas/hidroclimáticas via upload de CSV (casadas por município+ano) e enriquecimento automático com população estimada do IBGE
- **📊 Análise Robusta**: Cálculo de 12+ métricas de paisagem diferentes
- **📥 Exportação**: Download dos resultados em formato CSV
- **🗺️ Visualização**: Mapas interativos e gráficos das classes de uso do solo
- **🐳 Docker**: imagem e `docker-compose.yml` prontos para rodar sem instalar dependências localmente

---

## 🛠️ Tecnologias Utilizadas

### Principais Bibliotecas

Versões conforme [requirements.txt](requirements.txt) — mantenha esse arquivo como referência única, esta tabela pode ficar desatualizada:

| Biblioteca | Versão | Função |
|------------|--------|---------|
| `streamlit` | 1.58.0 | Interface web |
| `geemap` | 0.30.0 | Integração Google Earth Engine |
| `pylandstats` | 3.1.0 | Cálculo de métricas de paisagem |
| `geopandas` | 0.14.3 | Processamento de dados geoespaciais |
| `earthengine-api` | 0.1.394 | API Google Earth Engine |
| `rasterio` | 1.4.4 | Leitura/recorte do GeoTIFF enviado pelo usuário (fonte de dados alternativa) |
| `PyJWT` | 2.10.1 | Sessão de login por e-mail/senha (token assinado) |
| `bcrypt` | 4.2.1 | Hash de senha das contas por e-mail/senha |
| `Authlib` + `httpx` | 1.7.2 / 0.28.1 | OAuth do login com Google (opcional, via `st.login()`) |
| `cryptography` | 49.0.0 | Criptografia (Fernet) das credenciais salvas por usuário |
| `requests` | 2.34.2 | Chamadas à API do IBGE (localidades, malhas territoriais, população estimada) |
| `scipy` | 1.17.1 | Predição de anos futuros (potência fracionária da matriz de transição, cadeia de Markov) |

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
- Se quiser, crie em [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials), tipo "OAuth client ID" / "Web application"
- Preenche a seção `[auth]` (opcional) em `secrets.toml` — veja `.streamlit/secrets.toml.example`

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
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edite `.streamlit/secrets.toml` e preencha:

- `jwt_secret_key` (obrigatório): gere com `python -c "import secrets; print(secrets.token_hex(32))"` — assina a sessão do login por e-mail/senha
- `app_encryption_key` (obrigatório): gere com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `[auth]` (opcional): só se quiser o botão "Entrar com Google" — `client_id`, `client_secret` e `redirect_uri` da credencial OAuth do Google, e um `cookie_secret` aleatório

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
pip install -r requirements.txt
streamlit run app.py
```

Acesse `http://localhost:8501`.

### 4. Deploy em produção (HTTPS)

Fase 4 do roadmap: a stack de produção (HTTPS automático via [Caddy](https://caddyserver.com/) + Let's Encrypt, genérica para qualquer VPS com Docker) sobe com um único comando, rodado **no servidor**:

```bash
# no servidor, com o domínio já apontando (DNS tipo A) para o IP dele
# e .streamlit/secrets.toml já preenchido (jwt_secret_key, app_encryption_key,
# e opcionalmente [auth] se for usar o botão do Google)
./scripts/deploy.sh seu-dominio.exemplo.com
```

O script gera o `Caddyfile` a partir de `Caddyfile.example` e sobe `docker-compose.prod.yml`. Se estiver usando o login com Google, ajuste `[auth].redirect_uri` em `secrets.toml` e a credencial OAuth no Google Cloud Console para `https://SEU_DOMINIO/oauth2callback`. Se preferir uma plataforma gerenciada (Railway, Render, Streamlit Community Cloud) que já resolve HTTPS por conta própria, `docker-compose.prod.yml`/Caddy/`deploy.sh` não são necessários — use direto o `Dockerfile`.

Para backup de `data/app.db` (credenciais criptografadas por usuário), agende `./scripts/backup-db.sh` via `cron` — veja o cabeçalho do script para o exemplo de crontab e a variável opcional `BACKUP_REMOTE`.

Detalhes e decisões pendentes (qual servidor/domínio usar) em [ROADMAP.md](ROADMAP.md#fase-4--deploy).

---

## 🎮 Como Usar

### 1. Faça Login

Abra o app e crie uma conta na aba "Criar conta" (e-mail + senha) — ou, se o
botão "Entrar com Google" estiver disponível, use sua conta Google. Na
primeira vez, cole o JSON da sua conta de serviço do Earth Engine quando
solicitado — fica salvo criptografado para as próximas sessões (pode ser
atualizado depois no expander "🔑 Atualizar credenciais do Earth Engine").

> ⚠️ A sessão do login por e-mail/senha é guardada só na aba do navegador
> (não em cookie): um F5 na página desloga. O login com Google, quando
> disponível, sobrevive a um refresh.

### 2. Siga o Fluxo da Interface

#### **Passo 1: Área de interesse**

Escolha entre dois modos:

- **📌 Ponto + buffer**: use a ferramenta "Draw a marker" no mapa, selecione **apenas um ponto**, clique em "Export" e faça upload do GeoJSON exportado (ou de um shapefile do ponto compactado em `.zip` — `.shp`+`.shx`+`.dbf`+`.prj`; limite 10MB). **Obrigatório** se a fonte de dados (Passo 2) for MapBiomas; se a fonte for seu próprio GeoTIFF, esse upload é **opcional** — veja "modo raster inteiro" abaixo.
- **🏘️ Limite municipal (IBGE)**: escolha um estado e um município nos dois seletores (populados pela API do IBGE) — a área de interesse passa a ser o limite territorial oficial do município inteiro, com um preview do polígono no mapa. Não há slider de buffer nesse modo.

#### **Passo 2: Fonte dos dados de cobertura do solo**

Escolha entre:

- **MapBiomas (Google Earth Engine)**: padrão, usa a collection mais recente disponível (ver [🌍 Classes MapBiomas Suportadas](#-classes-mapbiomas-suportadas))
- **Meu raster (GeoTIFF)**: envie um ou **vários** rasters de cobertura do solo (limite 5GB cada). Requisitos:
  - Mesmos códigos de classe do MapBiomas (1=Floresta, 15=Pastagem etc.)
  - CRS qualquer: se estiver em coordenadas geográficas (graus), o app reprojeta **automaticamente** antes de calcular (zona UTM do ponto, SIRGAS 2000/Brazil Polyconic no modo raster inteiro, ou a zona UTM do centróide no modo município) — não precisa reprojetar manualmente antes de enviar. O arquivo convertido fica disponível para download na seção de resultados
  - **Modo ponto, com ponto enviado**: pode cobrir uma área bem maior que o buffer — o app recorta automaticamente a região ao redor do ponto selecionado
  - **Modo ponto, sem ponto enviado (modo raster inteiro)**: o app calcula as métricas para a extensão **inteira** do raster, sem recorte — útil quando o próprio arquivo já é a área de interesse
  - **Modo município**: o app recorta automaticamente pelo limite municipal selecionado no Passo 1
  - **Mais de um arquivo enviado**: cada um é processado separadamente e comparado ao final — se o nome do arquivo tiver um ano (ex.: `Corte_255_2010.tif`), a comparação vira uma série temporal (habilita a predição para anos futuros, ver abaixo); senão, usa a ordem de upload

#### **Passo 3: Configuração do Buffer**

> Só aparece no modo ponto+buffer, com um ponto enviado. No modo raster inteiro ou no modo município, esta etapa é pulada.

- Ajuste o raio do buffer (1.000-10.000m)
- Buffer maior = área de análise maior

#### **Passo 4: Calcular métricas**

- Clique no botão **"🧮 Calcular métricas"** — o cálculo não roda mais sozinho a cada interação, só quando você pede
- Acompanhe o andamento em tempo real: cada etapa (preparar área, conectar ao MapBiomas ou recortar o GeoTIFF, calcular métricas) aparece com seu próprio status, dentro de um painel expansível
- Os resultados ficam visíveis mesmo depois de outras ações na página (ex.: baixar o CSV), sem precisar recalcular

### 3. Visualize os Resultados

**Um arquivo (ou MapBiomas):**

- **Mapa da área**: Visualização do buffer ou do limite municipal aplicado (não aparece no modo raster inteiro, já que não há um ponto/buffer para mostrar)
- **Classes de uso**: Gráfico das classes encontradas
- **Métricas detalhadas**: cada métrica aparece em sua própria seção conforme é calculada, com gráfico de barras por classe + tabela, além da tabela consolidada com 12+ métricas
- **Download**: CSV das métricas e, se o GeoTIFF enviado precisou ser reprojetado automaticamente, também o raster convertido

**Vários arquivos (GeoTIFF):**

- Um resumo compacto por arquivo (mapa de classes + tabela), em painéis expansíveis
- Uma seção de **comparação entre arquivos**: um gráfico de linha por métrica, uma cor por classe de cobertura do solo, no eixo X o ano (ou a ordem de upload)
- Se 2+ arquivos tiverem ano identificável no nome: uma seção **"🔮 Predição para anos futuros"** — escolha os anos-alvo e veja a projeção da proporção de cada classe (cadeia de Markov), com tabela + gráfico + CSV
- Botão **"📥 Baixar relatório (HTML)"**: um arquivo autocontido com o resumo de cada arquivo e os gráficos comparativos — abra no navegador e use **Ctrl+P** para salvar como PDF

**Matriz socioecológica (SSE):** assim que você tiver ao menos uma análise salva, a seção **"🧬 Matriz socioecológica (SSE)"** (logo acima do Passo 1) mostra todas as suas análises agregadas numa matriz — anexe um CSV com variáveis socioeconômicas/hidroclimáticas (casadas por município+ano) para enriquecê-la, veja o heatmap de correlação e baixe o CSV combinado.

> ⚠️ Se a extração de dados reais do MapBiomas/Earth Engine falhar (ex.: buffer
> muito pequeno ou região sem cobertura no asset), o processamento é
> interrompido com uma mensagem de erro — o app nunca substitui por dados de
> exemplo. Aumente o raio do buffer, selecione outro ponto/município e tente
> de novo.

---

## 📍 Onde encontrar seus resultados

Resumo de cada resultado calculado, onde ele aparece na tela e como levá-lo pra fora do app. Tudo que fica marcado como "sim" em **Persiste?** continua visível mesmo depois de clicar em outros botões da página (ex.: um download) — o app guarda o resultado em `st.session_state` em vez de recalcular a cada interação do Streamlit.

| Resultado | Onde aparece na tela | Persiste? | Como exportar |
|---|---|---|---|
| Métrica por classe, uma a uma (gráfico + tabela) | Durante o cálculo, um expander por métrica (revelação progressiva) | Não — é o acompanhamento em tempo real do processamento | Os mesmos valores estão na tabela consolidada abaixo |
| Tabela consolidada de métricas por classe (12+ métricas) | Seção "📈 Métricas da paisagem", logo abaixo do mapa/gráfico de classes | Sim | Botão **"📥 Download CSV"** |
| Métricas de nível de paisagem (SHDI, CONTAG, MESH, PD, ED, LSI, SHEI, SIDI, SIEI, PR) | Cards ("🌎 Métricas da paisagem — nível global") logo após a tabela consolidada | Sim | Botão **"📥 Download CSV (métricas de paisagem)"** |
| Mapa da área de interesse (ponto + buffer) | Coluna esquerda, junto do gráfico de classes (não aparece no modo raster inteiro) | Sim | — (visual; sem export próprio) |
| Gráfico das classes de cobertura do solo | Coluna direita, junto do mapa da área | Sim | — (visual; sem export próprio) |
| GeoTIFF reprojetado automaticamente (quando o arquivo enviado estava em graus) | Logo abaixo da tabela consolidada, com uma explicação do porquê | Sim | Botão **"📥 Download GeoTIFF reprojetado"** |
| Resumo por arquivo (modo **multi-arquivo**: 2+ GeoTIFFs) | Um expander por arquivo — mapa + tabela + cards de paisagem | Sim | Incluído no relatório HTML (linha abaixo) |
| Comparação entre arquivos (modo multi-arquivo) | Seção "📊 Comparação entre arquivos", um gráfico por métrica, uma cor por classe | Sim | Incluído no relatório HTML (linha abaixo) |
| Predição para anos futuros (Markov, 2+ anos identificados) | Seção "🔮 Predição para anos futuros", logo após a comparação entre arquivos | Sim | Botão **"📥 Download CSV (predição)"** |
| Relatório completo do modo multi-arquivo | — | — | Botão **"📥 Baixar relatório (HTML)"** — abra no navegador e use **Ctrl+P** pra salvar como PDF |
| Matriz socioecológica (SSE): todas as suas análises salvas agregadas | Seção "🧬 Matriz socioecológica (SSE)", acima do fluxo de nova análise | Sim (lê direto do histórico salvo) | Botão **"📥 Download CSV (matriz socioecológica)"** |
| Métricas por município em lote (shapefile de municípios + 1 GeoTIFF) | Seção "📦 Métricas por município (lote via shapefile)", acima do fluxo de nova análise | Sim | Botão **"📥 Download planilha (.xlsx)"** (abas "paisagem"/"classe") ou os 2 botões de CSV equivalentes |

> Tudo isso (exceto a matriz socioecológica e o lote por município, que rodam em seções próprias) passa a existir só depois de clicar em **"🧮 Calcular métricas"** (Passo 4) — nada é calculado automaticamente antes disso.

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
├── app.py                          # Aplicação principal (Streamlit)
├── auth.py                         # Landing page + login/logout (e-mail/senha + Google opcional)
├── db.py                           # Persistência criptografada das credenciais GEE por usuário
├── requirements.txt                # Dependências Python
├── Dockerfile                      # Imagem da aplicação
├── docker-compose.yml              # Orquestração local (app + volumes)
├── docker-compose.prod.yml         # Stack de produção (app + Caddy/HTTPS)
├── Caddyfile.example               # Modelo de config do proxy reverso (produção)
├── scripts/
│   ├── deploy.sh                   # Deploy de produção em 1 comando (Fase 4)
│   └── backup-db.sh                # Backup datado de data/app.db (+ envio remoto opcional)
├── README.md                       # Este arquivo
├── ROADMAP.md                      # Status do projeto e próximas fases
├── data/
│   └── app.db                      # SQLite com as credenciais criptografadas (gerado em runtime)
└── .streamlit/
    ├── config.toml                 # maxUploadSize (5GB, para o GeoTIFF opcional)
    ├── secrets.toml.example        # Modelo de configuração de segredos
    └── secrets.toml                # Segredos locais (nunca commitado)
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

Para ativar logs detalhados:

```bash
streamlit run app.py --logger.level=debug
```

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
- [Streamlit](https://streamlit.io/) - Framework para aplicações web em Python

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

- [Documentação Streamlit](https://docs.streamlit.io/)
- [Google Earth Engine Docs](https://developers.google.com/earth-engine/)
- [PyLandStats Docs](https://pylandstats.readthedocs.io/)
- [MapBiomas Docs](https://mapbiomas.org/downloads)

---

**⭐ Se este projeto foi útil, considere dar uma estrela no GitHub!**
