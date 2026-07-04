# 🏞️ Landscape Metrics Extractor

![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Progresso](https://img.shields.io/badge/roadmap-87%2C5%25-yellow.svg)

> ℹ️ O link de demo online desta versão foi removido: a arquitetura de login e
> credenciais por usuário mudou (veja [ROADMAP.md](ROADMAP.md)) e a Fase 4
> (deploy público com HTTPS) ainda está pendente. Por enquanto, rode
> localmente ou via Docker — veja [🔧 Instalação](#-instalação).
>
> **Progresso: 87,5%** — Fases 1-3 (landing page, login, credenciais por
> usuário) concluídas; Fase 4 (deploy) está preparada mas não executada.
> Detalhamento por fase em [ROADMAP.md](ROADMAP.md#progresso-geral-875).

**Aplicativo Web para extração de métricas de paisagem de pontos de interesse a partir da base de dados do MapBiomas**

Desenvolvido por [Pedro Higuchi](https://twitter.com/pe_hi) | Contato: higuchip@gmail.com

---

## 📖 Descrição

O **Landscape Metrics Extractor** é uma aplicação web desenvolvida em Streamlit que permite extrair e analisar métricas de paisagem para pontos específicos no território brasileiro. A aplicação utiliza dados do MapBiomas através do Google Earth Engine e calcula métricas detalhadas usando a biblioteca PyLandStats.

Cada usuário faz login com sua conta Google e cadastra sua **própria** credencial de conta de serviço do Earth Engine — não há mais uma conta de serviço única compartilhada entre todos os usuários. Veja o estado detalhado do projeto e o que falta em [ROADMAP.md](ROADMAP.md).

### 🎯 Funcionalidades Principais

- **🔑 Login com Google**: acesso à ferramenta só depois de autenticado
- **🔒 Credenciais por usuário**: cada usuário cadastra e usa sua própria conta de serviço do Earth Engine, guardada criptografada
- **📍 Seleção Interativa**: Interface com mapas para seleção de pontos de interesse
- **🛰️ Dados MapBiomas**: acesso à collection mais recente disponível (com fallback automático para collections anteriores)
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
| `streamlit` | 1.58.0 | Interface web, login (`st.login`) |
| `geemap` | 0.30.0 | Integração Google Earth Engine |
| `pylandstats` | 3.1.0 | Cálculo de métricas de paisagem |
| `geopandas` | 0.14.3 | Processamento de dados geoespaciais |
| `earthengine-api` | 0.1.394 | API Google Earth Engine |
| `Authlib` | 1.7.2 | OAuth do login com Google |
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

### 2. Credenciais OAuth do Google (uma vez, por quem hospeda o app)

- Criadas em [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials), tipo "OAuth client ID" / "Web application"
- Necessárias para o login (`[auth]` em `secrets.toml`) — veja `.streamlit/secrets.toml.example`

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

- `[auth]`: `client_id`, `client_secret` e `redirect_uri` da credencial OAuth do Google, e um `cookie_secret` aleatório
- `app_encryption_key`: gere com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

Essas duas configurações protegem o login e a criptografia das credenciais do Earth Engine — **nunca** faça commit desse arquivo (já está no `.gitignore`).

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

Fase 4 do roadmap: já existe uma stack pronta para publicar o app com HTTPS automático (via [Caddy](https://caddyserver.com/) + Let's Encrypt), genérica para qualquer VPS com Docker:

```bash
cp Caddyfile.example Caddyfile
# edite Caddyfile com o domínio real (precisa já apontar para o IP do servidor)
docker compose -f docker-compose.prod.yml up -d --build
```

Antes de rodar em produção, ajuste também `[auth].redirect_uri` em `secrets.toml` (e na credencial OAuth no Google Cloud Console) para `https://SEU_DOMINIO/oauth2callback`. Se preferir uma plataforma gerenciada (Railway, Render, Streamlit Community Cloud) que já resolve HTTPS por conta própria, `docker-compose.prod.yml`/Caddy não são necessários — use direto o `Dockerfile`. Detalhes e decisões pendentes em [ROADMAP.md](ROADMAP.md#fase-4--deploy).

---

## 🎮 Como Usar

### 1. Faça Login

Abra o app e clique em "Entrar com Google". Na primeira vez, cole o JSON da
sua conta de serviço do Earth Engine quando solicitado — fica salvo
criptografado para as próximas sessões (pode ser atualizado depois no
expander "🔑 Atualizar credenciais do Earth Engine").

### 2. Siga o Fluxo da Interface

#### **Passo 1: Seleção do Ponto**

- Use a ferramenta "Draw a marker" no mapa
- Selecione **apenas um ponto** de interesse
- Clique em "Export" para gerar o arquivo GeoJSON

#### **Passo 2: Upload do Arquivo**

- Faça upload do arquivo GeoJSON exportado
- Limite: 10MB, apenas arquivos .geojson

#### **Passo 3: Configuração do Buffer**

- Ajuste o raio do buffer (1.000-10.000m)
- Buffer maior = área de análise maior

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
├── auth.py                         # Landing page + login/logout com Google
├── db.py                           # Persistência criptografada das credenciais GEE por usuário
├── requirements.txt                # Dependências Python
├── Dockerfile                      # Imagem da aplicação
├── docker-compose.yml              # Orquestração local (app + volumes)
├── docker-compose.prod.yml         # Stack de produção (app + Caddy/HTTPS)
├── Caddyfile.example               # Modelo de config do proxy reverso (produção)
├── README.md                       # Este arquivo
├── ROADMAP.md                      # Status do projeto e próximas fases
├── data/
│   └── app.db                      # SQLite com as credenciais criptografadas (gerado em runtime)
└── .streamlit/
    ├── secrets.toml.example        # Modelo de configuração de segredos
    └── secrets.toml                # Segredos locais (nunca commitado)
```

---

## 🔒 Segurança

### Validações Implementadas

- ✅ **Login obrigatório**: acesso à ferramenta só após autenticação Google (`st.login`)
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
