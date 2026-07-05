# 10 — Integrações Externas

## Google Earth Engine

| Aspecto | Detalhe |
| --- | --- |
| SDK | `earthengine-api` (`import ee`) |
| Autenticação | Conta de serviço (JSON) cadastrada por cada usuário — não há credencial compartilhada |
| Endpoint | `https://earthengine-highvolume.googleapis.com` (ver decisão de projeto em `app.initialize_ee`) |
| Uso | Leitura de imagens/rasters do MapBiomas via `sampleRectangle` (método principal) e `reduceRegion` (fallback) |
| Pré-requisito do usuário | Conta em earthengine.google.com + conta de serviço no GCP com a Earth Engine API habilitada |
| Falhas tratadas | Asset indisponível (tenta collection anterior), erro de inicialização (mensagem com possíveis causas), pixels insuficientes na região (erro explícito) |

## MapBiomas

Não é uma integração separada tecnicamente — são assets públicos acessados através do Earth
Engine. O app tenta, em ordem de preferência, os assets oficiais de Collection 9, 8, 7 e 6
(`app.py`, lista `mapbiomas_assets`), usando o primeiro que responder com bandas válidas.

> **Limitação conhecida**: a legenda de classes (`legend_keys` em `app.py`) é fixa e otimizada
> para o esquema aproximado da Collection 9. Se o fallback cair para uma collection mais antiga
> com códigos de classe diferentes, a legenda pode não corresponder exatamente.

## Google OAuth (opcional)

| Aspecto | Detalhe |
| --- | --- |
| Biblioteca | Nativa do Streamlit (`st.login()` / `st.user` / `st.logout()`), com `Authlib` + `httpx` como dependências |
| Ativação | Só quando a seção `[auth]` existe em `.streamlit/secrets.toml` — do contrário, o botão simplesmente não aparece |
| Configuração necessária | `client_id`, `client_secret`, `redirect_uri`, `server_metadata_url`, `cookie_secret` |
| Onde configurar no Google Cloud | [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials) — credencial tipo "OAuth client ID" / "Web application" |
| Sessão | Gerenciada pelo próprio Streamlit (cookie assinado) — sobrevive a um refresh (F5), diferente do modo e-mail/senha |

## Webhooks

Nenhum webhook de entrada ou saída é usado ou exposto pelo sistema.

## Processamento assíncrono / filas

Nenhuma fila de mensagens ou processamento em background é usada — todas as chamadas às
integrações acima são síncronas, dentro do próprio processo Streamlit, bloqueando a UI durante a
execução.
