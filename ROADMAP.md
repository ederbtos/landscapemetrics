# Roadmap — Landscape Metrics Extractor

## Progresso geral: 87,5%

| Fase | Descrição | Status | % |
| --- | --- | --- | --- |
| 1 | Landing page | ✅ Concluída | 100% |
| 2 | Login (Google OAuth) | ✅ Concluída | 100% |
| 3 | Credenciais por usuário | ✅ Concluída | 100% |
| 4 | Deploy (HTTPS) | 🔧 Preparada, falta executar | 50% |

> O percentual mede fases do roadmap entregues. A Fase 4 tem toda a
> configuração de deploy pronta ([docker-compose.prod.yml](docker-compose.prod.yml),
> [Caddyfile.example](Caddyfile.example)), mas os 100% só são atingidos com uma
> publicação real, o que depende de uma decisão que só quem hospeda o app pode
> tomar: qual servidor/domínio usar. Ver "Fase 4 — Deploy" abaixo.

## Status atual (2026-07-04)

### ✅ Concluído

- **Dependências corrigidas**: `requirements.txt` tinha pins incompatíveis com ambientes atuais
  (`pylandstats==3.0.0` não tem wheel para Windows/Python 3.13; `geemap==0.30.0` quebra com
  `setuptools>=81` e `ipython>=9`). Ajustado para `pylandstats==3.1.0`, `setuptools<81`, `ipython<9`.
- **Dockerfile**: imagem baseada em `python:3.11-slim`, com `libexpat1`/`libgomp1` (dependências
  nativas do rasterio/GDAL) e healthcheck em `/_stcore/health`.
- **docker-compose.yml**: sobe o app expondo a porta 8501 e montando `.streamlit/secrets.toml`
  como volume somente-leitura (as credenciais nunca vão para dentro da imagem).
- **`.streamlit/secrets.toml.example`**: modelo do arquivo de segredos do app (OAuth do Google
  para login e `app_encryption_key` para cifrar as credenciais salvas) — não contém mais a
  credencial de conta de serviço do Earth Engine, que passou a ser por usuário (Fase 3).
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
- **Remoção dos dados de fallback sintéticos** ([app.py](app.py)): quando a extração de pixels do
  MapBiomas/Earth Engine falhava, o app anteriormente substituía os dados por uma matriz fixa
  fictícia ("Santa Catarina") e seguia calculando métricas/CSV como se fossem reais. Agora, uma
  falha na extração real interrompe o processamento (`st.stop()`) com uma mensagem explicando a
  causa provável — nenhuma métrica é exibida ou exportada sem dados reais por trás.
- **Preparação da Fase 4 (deploy)**: [docker-compose.prod.yml](docker-compose.prod.yml) sobe o app
  atrás de um proxy reverso [Caddy](https://caddyserver.com/) que emite e renova HTTPS
  automaticamente via Let's Encrypt, genérico para qualquer VPS com Docker (não amarrado a um
  provedor específico). Modelo de configuração em
  [Caddyfile.example](Caddyfile.example).

### ⚠️ Bloqueio conhecido

- Sem as credenciais do Earth Engine cadastradas pelo próprio usuário (fluxo da Fase 3), a
  aplicação sobe normalmente mas para na etapa de inicialização do Earth Engine — comportamento
  esperado, não um bug.

---

## Próxima fase

### Fase 4 — Deploy

O que falta é só a execução — decisão de infraestrutura que cabe a quem for hospedar o app:

1. Escolher onde rodar (qualquer servidor com Docker: VPS próprio, ex. Hetzner/DigitalOcean/OVH,
   ou uma plataforma gerenciada como Railway/Render que já resolve HTTPS por você — nesse caso
   `docker-compose.prod.yml`/Caddy não são necessários).
2. Se for VPS com Docker: apontar um domínio (registro DNS tipo A) para o IP do servidor, liberar
   as portas 80/443 no firewall, copiar `Caddyfile.example` para `Caddyfile` com o domínio real, e
   rodar `docker compose -f docker-compose.prod.yml up -d --build`.
3. Atualizar `[auth].redirect_uri` em `.streamlit/secrets.toml` (e na credencial OAuth no Google
   Cloud Console) para `https://SEU_DOMINIO/oauth2callback`.
4. Definir onde `data/app.db` (credenciais criptografadas por usuário) será persistido/salvo em
   backup fora do ciclo de vida do container — hoje é um volume local (`./data`), que precisa
   sobreviver a rebuilds/migrações do servidor.

---

## Como rodar hoje

Detalhes completos (pré-requisitos, geração do `app_encryption_key`, credenciais OAuth) em [README.md](README.md#-instalação). Resumo:

### Local (sem Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml: seção [auth] (OAuth do Google) e app_encryption_key
streamlit run app.py
```

### Docker

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml: seção [auth] (OAuth do Google) e app_encryption_key
docker compose up --build
```

Acesse `http://localhost:8501`. Depois de logado, cada usuário cola sua própria credencial de conta de serviço do Earth Engine na própria interface (não vai em `secrets.toml`).
