# Roadmap — Landscape Metrics Extractor

## Progresso geral: 93,75%

| Fase | Descrição | Status | % |
| --- | --- | --- | --- |
| 1 | Landing page | ✅ Concluída | 100% |
| 2 | Login (e-mail/senha + JWT, com Google OAuth opcional) | ✅ Concluída | 100% |
| 3 | Credenciais por usuário | ✅ Concluída | 100% |
| 4 | Deploy (HTTPS) | 🔧 Automatizada (1 comando), falta decisão de infra + execução | 75% |

> O percentual mede fases do roadmap entregues. A Fase 4 tem toda a mecânica pronta e
> automatizada em um único comando ([scripts/deploy.sh](scripts/deploy.sh), usando
> [docker-compose.prod.yml](docker-compose.prod.yml) e [Caddyfile.example](Caddyfile.example)),
> mas os 100% só são atingidos com uma publicação real, o que depende de uma decisão que só quem
> hospeda o app pode tomar: qual servidor/domínio usar. Ver "Fase 4 — Deploy" abaixo.

## Status atual (2026-07-04)

### ✅ Concluído

- **Dependências corrigidas**: `requirements.txt` tinha pins incompatíveis com ambientes atuais
  (`pylandstats==3.0.0` não tem wheel para Windows/Python 3.13; `geemap==0.30.0` quebra com
  `setuptools>=81` e `ipython>=9`). Ajustado para `pylandstats==3.1.0`, `setuptools<81`, `ipython<9`.
- **Dockerfile**: imagem baseada em `python:3.11-slim`, com `libexpat1`/`libgomp1` (dependências
  nativas do rasterio/GDAL) e healthcheck em `/_stcore/health`.
- **docker-compose.yml**: sobe o app expondo a porta 8501 e montando `.streamlit/secrets.toml`
  como volume somente-leitura (as credenciais nunca vão para dentro da imagem).
- **`.streamlit/secrets.toml.example`**: modelo do arquivo de segredos do app (`jwt_secret_key`
  para assinar a sessão de login, seção `[auth]` opcional para o Google OAuth e
  `app_encryption_key` para cifrar as credenciais salvas) — não contém a credencial de conta de
  serviço do Earth Engine, que é por usuário (Fase 3).
- **Fase 1 — Landing page** ([auth.py](auth.py)): tela inicial explicando o app antes do login,
  como primeira renderização do próprio `app.py` (sem app multi-página) quando o usuário ainda
  não está autenticado.
- **Fase 2 — Login, dois modos** ([auth.py](auth.py), [db.py](db.py)):
  - **E-mail/senha (sempre disponível)**: cadastro aberto, senha nunca em texto puro — só o hash
    bcrypt na tabela `users` de `data/app.db`. Sessão representada por um JWT (HS256, assinado com
    `jwt_secret_key`) guardado em `st.session_state` — não sobrevive a um refresh (F5) da página,
    já que não é persistido em cookie.
  - **Google OAuth (opcional)**: aparece como botão extra na landing page quando a seção `[auth]`
    de `secrets.toml` está preenchida com uma credencial OAuth real do Google Cloud Console. Usa
    `st.login()`/`st.user`/`st.logout()` nativos do Streamlit; a sessão sobrevive a um refresh
    (cookie assinado pelo próprio Streamlit), ao contrário do modo e-mail/senha.
  - Os dois modos compartilham o e-mail como chave de identidade em `data/app.db` — ver
    `get_current_user_email()`. Badge do usuário e botão de logout na sidebar (independente do
    modo usado) em [app.py](app.py) linha 283.
- **Fase 3 — Credenciais por usuário** ([db.py](db.py), [app.py](app.py) linhas 285-297): cada
  usuário cola o JSON da própria conta de serviço do Earth Engine, que é criptografado com Fernet
  (`app_encryption_key` em `secrets.toml`) e persistido em SQLite (`data/app.db`), com formulário
  de atualização das credenciais a qualquer momento.
- **Remoção dos dados de fallback sintéticos** ([app.py](app.py)): quando a extração de pixels do
  MapBiomas/Earth Engine falhava, o app anteriormente substituía os dados por uma matriz fixa
  fictícia ("Santa Catarina") e seguia calculando métricas/CSV como se fossem reais. Agora, uma
  falha na extração real interrompe o processamento (`st.stop()`) com uma mensagem explicando a
  causa provável — nenhuma métrica é exibida ou exportada sem dados reais por trás.
- **Fonte de dados alternativa: GeoTIFF próprio** ([app.py](app.py), função
  `extract_landscape_from_tif`): além do MapBiomas via Earth Engine, o usuário pode escolher
  ("3) Fonte dos dados de cobertura do solo") enviar seu próprio raster GeoTIFF (até 5GB — ver
  `MAX_TIF_SIZE` e `.streamlit/config.toml`/`server.maxUploadSize`). O ponto e o buffer definidos
  na interface recortam esse raster localmente via `rasterio`/`pyproj`/`shapely` (o raster pode
  cobrir uma área bem maior que o buffer). Exige CRS projetado (metros) — rejeitado explicitamente
  se for geográfico (graus), já que o buffer é definido em metros — e assume os mesmos códigos de
  classe do MapBiomas (a legenda usada no restante do app não muda). A resolução real do pixel é
  lida do próprio raster (em vez do valor fixo de 30m usado no caminho MapBiomas/GEE) e passada a
  `pls.Landscape`. Segue a mesma regra de "falhar explicitamente" das demais fontes: sem pixels
  válidos no buffer, o processamento para (`st.stop()`) em vez de gerar uma métrica a partir de
  dados incompletos.
- **Botão "Calcular métricas" + pipeline em tempo real** ([app.py](app.py)): o cálculo deixou de
  rodar automaticamente a cada interação do Streamlit (o que reprocessaria tudo — inclusive
  uploads grandes de GeoTIFF — a cada rerun) e passou a ser disparado por um botão explícito.
  Dentro de `st.status(..., expanded=True)`, cada etapa (preparar área de interesse, conectar ao
  MapBiomas ou recortar o GeoTIFF, calcular métricas no PyLandStats) aparece em tempo real com seu
  próprio ícone de andamento/concluído/erro. O resultado (array de classes, `Landscape` do
  PyLandStats, tabela de métricas, geometrias do buffer) é guardado em `st.session_state` para
  sobreviver a reruns causados por outros widgets (ex.: o botão de download do CSV) sem precisar
  refazer chamadas ao Earth Engine ou reprocessar o GeoTIFF.
- **Preparação da Fase 4 (deploy)**: [docker-compose.prod.yml](docker-compose.prod.yml) sobe o app
  atrás de um proxy reverso [Caddy](https://caddyserver.com/) que emite e renova HTTPS
  automaticamente via Let's Encrypt, genérico para qualquer VPS com Docker (não amarrado a um
  provedor específico). Modelo de configuração em
  [Caddyfile.example](Caddyfile.example).
- **Deploy em um comando**: [scripts/deploy.sh](scripts/deploy.sh) automatiza tudo que não depende
  de uma decisão de infraestrutura — gera o `Caddyfile` a partir do domínio informado e sobe
  `docker-compose.prod.yml`. O que resta é só escolher servidor/domínio (ver "Fase 4 — Deploy"
  abaixo) e rodar `./scripts/deploy.sh seu-dominio.com` no servidor.
- **Backup de `data/app.db`**: [scripts/backup-db.sh](scripts/backup-db.sh) gera dumps datados
  localmente (mantendo os 30 mais recentes) e, se a variável `BACKUP_REMOTE` estiver definida,
  envia via `rsync` para fora do servidor — pronto para agendar via `cron`.
- **Validação end-to-end confirmada pelo usuário (2026-07-04)**: fluxo completo de extração de
  métricas com credencial real do Earth Engine testado com sucesso (login → credenciais →
  seleção de ponto → cálculo de métricas via MapBiomas/GEE).
- **Configuração Docker validada localmente (2026-07-04)**: `secrets.toml` preenchido e stack
  local (`docker-compose.yml`) testada com sucesso — reduz o risco da execução da Fase 4, mas o
  deploy em si (servidor/domínio públicos) ainda não foi feito.

### 🔄 Mudança de arquitetura (2026-07-04): login por e-mail/senha + JWT, com Google OAuth opcional

A Fase 2 originalmente usava só `st.login("google")` (OAuth nativo do Streamlit). O app estava
configurado com valores fictícios (`fake-client-id`) e retornava `Erro 401: cliente inválido` do
Google. Em vez de depender só da credencial OAuth, foi adicionado um sistema de contas próprio
(e-mail/senha) como modo sempre disponível, e o Google OAuth virou um modo adicional opcional:

- Cadastro aberto por e-mail/senha (sem confirmação de e-mail), com hash bcrypt em `data/app.db`
  (tabela `users`), nunca em texto puro.
- Sessão via JWT assinado (`jwt_secret_key`) guardado em `st.session_state` — trade-off aceito:
  simples de implementar, mas a sessão não sobrevive a um refresh da página (sem cookie).
- Login com Google continua disponível (`st.login()`, sem argumento de provedor — `secrets.toml`
  usa a seção `[auth]` de provedor único, não `[auth.google]`) quando configurado com credencial
  OAuth real; convive com o modo e-mail/senha, cada um cuidando da própria sessão.
- Depende de `PyJWT` e `bcrypt` (novo) além de `Authlib`/`httpx` (mantidos para o modo Google).

### ⚠️ Bloqueio conhecido

- Sem as credenciais do Earth Engine cadastradas pelo próprio usuário (fluxo da Fase 3), a
  aplicação sobe normalmente mas para na etapa de inicialização do Earth Engine — comportamento
  esperado, não um bug.
- O e-mail de cadastro não é verificado (sem confirmação por e-mail) — é só uma chave de conta
  local, não uma prova de propriedade do endereço.
- Sessão de login não sobrevive a um refresh (F5) da página, por guardar o JWT em
  `st.session_state` em vez de cookie.

---

## Próxima fase

### Fase 4 — Deploy

Toda a mecânica está automatizada; o que falta é só a execução — decisão de infraestrutura que
cabe a quem for hospedar o app:

1. Escolher onde rodar (qualquer servidor com Docker: VPS próprio, ex. Hetzner/DigitalOcean/OVH,
   ou uma plataforma gerenciada como Railway/Render que já resolve HTTPS por você — nesse caso
   `docker-compose.prod.yml`/Caddy não são necessários).
2. Se for VPS com Docker: apontar um domínio (registro DNS tipo A) para o IP do servidor, liberar
   as portas 80/443 no firewall, preencher `.streamlit/secrets.toml` (a partir do
   `.streamlit/secrets.toml.example`, com `jwt_secret_key` e `app_encryption_key` reais) e rodar
   `./scripts/deploy.sh seu-dominio.com` — o script gera o `Caddyfile` e sobe a stack.
3. Agendar `./scripts/backup-db.sh` via `cron` (opcionalmente com `BACKUP_REMOTE` apontando para
   fora do servidor) para que `data/app.db` sobreviva a rebuilds/migrações — a mecânica já existe,
   falta só decidir o destino externo do backup.

---

## Como rodar hoje

Detalhes completos (pré-requisitos, geração das chaves) em [README.md](README.md#-instalação). Resumo:

### Local (sem Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml: jwt_secret_key e app_encryption_key
streamlit run app.py
```

### Docker

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml: jwt_secret_key e app_encryption_key
docker compose up --build
```

Acesse `http://localhost:8501`. Crie uma conta (e-mail/senha) na aba "Criar conta" — ou, se a
seção `[auth]` do Google estiver configurada em `secrets.toml`, use o botão "Entrar com Google" —
e, depois de logado, cole sua própria credencial de conta de serviço do Earth Engine na interface
(não vai em `secrets.toml`).
