# Roadmap — Landscape Metrics Extractor

## Status atual (2026-07-04)

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
- **Fase 1 — Landing page** ([auth.py](auth.py)): tela inicial explicando o app antes do login,
  como primeira renderização do próprio `app.py` (sem app multi-página) quando o usuário ainda
  não está autenticado.
- **Fase 2 — Login** ([auth.py](auth.py)): autenticação via `st.login("google")` (OAuth nativo do
  Streamlit), configurada pela seção `[auth]` de `.streamlit/secrets.toml`. Badge do usuário e
  botão de logout na sidebar ([app.py](app.py) linha 216).
- **Fase 3 — Credenciais por usuário** ([db.py](db.py), [app.py](app.py) linhas 219-239): cada
  usuário cola o JSON da própria conta de serviço do Earth Engine, que é criptografado com Fernet
  (`app_encryption_key` em `secrets.toml`) e persistido em SQLite (`data/app.db`), com formulário
  de atualização das credenciais a qualquer momento.

### ⚠️ Bloqueio conhecido

- Sem as credenciais do Earth Engine cadastradas pelo próprio usuário (fluxo da Fase 3), a
  aplicação sobe normalmente mas para na etapa de inicialização do Earth Engine.

---

## Próxima fase

### Fase 4 — Deploy

- Publicar a imagem Docker em um ambiente com HTTPS antes de expor login/credenciais reais
  (evitar transmitir segredos em texto puro).
- Decisões pendentes: provedor de hospedagem, domínio, `redirect_uri` de produção para o OAuth do
  Google, e onde persistir `data/app.db` fora do ciclo de vida do container.

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
