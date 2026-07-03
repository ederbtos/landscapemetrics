# Roadmap — Landscape Metrics Extractor

## Status atual (2026-07-03)

### ✅ Concluído
- **Dependências corrigidas**: `requirements.txt` tinha pins incompatíveis com ambientes atuais
  (`pylandstats==3.0.0` não tem wheel para Windows/Python 3.13; `geemap==0.30.0` quebra com
  `setuptools>=81` e `ipython>=9`). Ajustado para `pylandstats==3.1.0`, `setuptools<81`, `ipython<9`.
- **Dockerfile**: imagem baseada em `python:3.11-slim`, com `libexpat1`/`libgomp1` (dependências
  nativas do rasterio/GDAL) e healthcheck em `/_stcore/health`.
- **docker-compose.yml**: sobe o app expondo a porta 8501 e montando `.streamlit/secrets.toml`
  como volume somente-leitura (as credenciais nunca vão para dentro da imagem).
- **`.streamlit/secrets.toml.example`**: modelo do arquivo de credenciais de conta de serviço do
  Google Earth Engine.

### ⚠️ Bloqueio conhecido
- O app depende de uma conta de serviço do Google Earth Engine configurada em
  `.streamlit/secrets.toml` (ou credenciais locais via `earthengine authenticate`). Sem isso,
  a aplicação sobe normalmente mas para na etapa de inicialização do Earth Engine.

---

## Próximas fases

### Fase 1 — Landing page
- Página inicial simples explicando o que o app faz, antes do usuário entrar na ferramenta.
- Decisão pendente: página estática separada vs. primeira tela de um app multi-página do
  Streamlit (`st.navigation` / pasta `pages/`).

### Fase 2 — Login
- Mecanismo de autenticação para identificar o usuário antes de liberar o uso do app.
- Decisão pendente: login simples (usuário/senha local) vs. OAuth (Google) vs. link mágico por
  e-mail. Afeta diretamente a Fase 3.

### Fase 3 — Credenciais por usuário
- Cada usuário poderá inserir suas próprias credenciais do Google Earth Engine para rodar as
  análises com sua própria cota/projeto GCP, em vez de depender de uma única conta de serviço
  compartilhada.
- Decisão pendente: as credenciais são digitadas a cada sessão (guardadas só em memória,
  mais simples e mais seguro) ou persistidas entre sessões (exige banco de dados e criptografia
  em repouso, mais complexo)?

### Fase 4 — Deploy
- Publicar a imagem Docker em um ambiente com HTTPS antes de expor login/credenciais reais
  (evitar transmitir segredos em texto puro).

---

## Como rodar hoje

### Local (sem Docker)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml com sua conta de serviço do GEE
streamlit run app.py
```

### Docker
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml com sua conta de serviço do GEE
docker compose up --build
```

Acesse http://localhost:8501.
