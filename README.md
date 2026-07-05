# 🏞️ Landscape Metrics Extractor

![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Progresso](https://img.shields.io/badge/roadmap-93%2C75%25-yellow.svg)

> ℹ️ O link de demo online desta versão foi removido: a arquitetura de login e
> credenciais por usuário mudou (veja [ROADMAP.md](ROADMAP.md)) e a Fase 4
> (deploy público com HTTPS) ainda está pendente de execução. Por enquanto,
> rode localmente ou via Docker — veja [🔧 Instalação](#-instalação).
>
> **Progresso: 93,75%** — Fases 1-3 (landing page, login, credenciais por
> usuário) concluídas; Fase 4 (deploy) está totalmente automatizada em
> [scripts/deploy.sh](scripts/deploy.sh), faltando só a decisão de
> servidor/domínio e a execução. Detalhamento por fase em
> [ROADMAP.md](ROADMAP.md#progresso-geral-9375).

**Aplicativo Web para extração de métricas de paisagem de pontos de interesse a partir da base de dados do MapBiomas**

Desenvolvido por [Pedro Higuchi](https://twitter.com/pe_hi) | Contato: higuchip@gmail.com

---

## 📖 Descrição

O **Landscape Metrics Extractor** é uma aplicação web desenvolvida em Streamlit que permite extrair e analisar métricas de paisagem para pontos específicos no território brasileiro. A aplicação utiliza dados do MapBiomas através do Google Earth Engine e calcula métricas detalhadas usando a biblioteca PyLandStats.

Cada usuário faz login (por e-mail/senha ou, opcionalmente, com Google) e cadastra sua **própria** credencial de conta de serviço do Earth Engine — não há mais uma conta de serviço única compartilhada entre todos os usuários. Veja o estado detalhado do projeto e o que falta em [ROADMAP.md](ROADMAP.md).

### 🎯 Funcionalidades Principais

- **🔑 Login por e-mail/senha (+ Google opcional)**: acesso à ferramenta só depois de autenticado, com cadastro aberto por e-mail/senha e um botão extra "Entrar com Google" quando configurado
- **🔒 Credenciais por usuário**: cada usuário cadastra e usa sua própria conta de serviço do Earth Engine, guardada criptografada
- **📍 Seleção Interativa**: Interface com mapas para seleção de pontos de interesse
- **🛰️ Dados MapBiomas**: acesso à collection mais recente disponível (com fallback automático para collections anteriores)
- **📤 GeoTIFF próprio (opcional)**: alternativa ao MapBiomas/Earth Engine — envie seu próprio raster de cobertura do solo (até 5GB, CRS projetado, códigos de classe MapBiomas) e o app recorta a área do buffer automaticamente
- **🧮 Cálculo sob demanda**: o processamento só roda quando você clica em "Calcular métricas", com cada etapa visível em tempo real (não recalcula sozinho a cada interação com a página)
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

### Fontes de Dados

- **MapBiomas**: dados de uso e cobertura da terra (tenta Collection 9 e recua para 8/7/6 conforme disponibilidade)
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

#### **Passo 1: Seleção do Ponto**

- Use a ferramenta "Draw a marker" no mapa
- Selecione **apenas um ponto** de interesse
- Clique em "Export" para gerar o arquivo GeoJSON

#### **Passo 2: Upload do Arquivo**

- Faça upload do arquivo GeoJSON exportado
- Limite: 10MB, apenas arquivos .geojson

#### **Passo 3: Fonte dos dados de cobertura do solo**

Escolha entre:

- **MapBiomas (Google Earth Engine)**: padrão, usa a collection mais recente disponível (ver [🌍 Classes MapBiomas Suportadas](#-classes-mapbiomas-suportadas))
- **Meu raster (GeoTIFF)**: envie seu próprio raster de cobertura do solo (limite 5GB). Requisitos:
  - CRS **projetado** (ex.: UTM), não geográfico (graus) — o buffer é definido em metros
  - Mesmos códigos de classe do MapBiomas (1=Floresta, 15=Pastagem etc.)
  - Pode cobrir uma área bem maior que o buffer: o app recorta automaticamente a região ao redor do ponto selecionado

#### **Passo 4: Configuração do Buffer**

- Ajuste o raio do buffer (1.000-10.000m)
- Buffer maior = área de análise maior

#### **Passo 5: Calcular métricas**

- Clique no botão **"🧮 Calcular métricas"** — o cálculo não roda mais sozinho a cada interação, só quando você pede
- Acompanhe o andamento em tempo real: cada etapa (preparar área, conectar ao MapBiomas ou recortar o GeoTIFF, calcular métricas) aparece com seu próprio status, dentro de um painel expansível
- Os resultados ficam visíveis mesmo depois de outras ações na página (ex.: baixar o CSV), sem precisar recalcular

### 3. Visualize os Resultados

- **Mapa da área**: Visualização do buffer aplicado
- **Classes de uso**: Gráfico das classes encontradas
- **Métricas detalhadas**: Tabela com 12+ métricas
- **Download**: Arquivo CSV formatado

> ⚠️ Se a extração de dados reais do MapBiomas/Earth Engine falhar (ex.: buffer
> muito pequeno ou região sem cobertura no asset), o processamento é
> interrompido com uma mensagem de erro — o app nunca substitui por dados de
> exemplo. Aumente o raio do buffer ou selecione outro ponto e tente de novo.

---

## 📊 Métricas Calculadas

| Métrica | Descrição | Unidade |
|---------|-----------|---------|
| `total_area` | Área total da classe | ha |
| `proportion_of_landscape` | Proporção na paisagem | % |
| `number_of_patches` | Número de manchas | - |
| `largest_patch_index` | Índice da maior mancha | % |
| `total_edge` | Total de bordas | m |
| `landscape_shape_index` | Índice de forma da paisagem | - |
| `area_mn` | Área média das manchas | ha |
| `perimeter_mn` | Perímetro médio | m |
| `shape_index_mn` | Índice de forma médio | - |
| `fractal_dimension_mn` | Dimensão fractal média | - |
| `euclidean_nearest_neighbor_mn` | Distância média ao vizinho mais próximo | m |

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
- ✅ **Tamanho de arquivo**: Máximo 10MB
- ✅ **Tipos permitidos**: Apenas .geojson
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

```text
❌ O GeoTIFF precisa estar em uma projeção métrica (ex.: UTM)
```

**Solução**: reprojete o raster para um CRS projetado (ex.: a zona UTM correspondente) antes de enviar — um CRS geográfico (graus) tornaria o buffer em metros incorreto.

```text
❌ A área do buffer não intersecta o raster enviado.
```

**Solução**: confirme que o ponto selecionado está dentro da área coberta pelo raster, ou aumente o buffer.

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
