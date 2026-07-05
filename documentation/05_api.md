# 05 — API

## Não há uma API REST/HTTP própria

O sistema é um script Streamlit (ver [02_architecture.md](02_architecture.md)) — não expõe
endpoints HTTP customizados para consumo por outros sistemas. Toda interação acontece pela UI
renderizada pelo Streamlit, dentro do mesmo processo que executa a lógica de negócio.

O único endpoint HTTP relevante é o de infraestrutura do próprio Streamlit:

| Rota | Uso |
| --- | --- |
| `GET /_stcore/health` | Healthcheck usado pelo Docker (`HEALTHCHECK` no [Dockerfile](../Dockerfile)) |

Se uma futura integração via API for necessária, ela precisaria ser construída do zero (ex.:
extraindo a lógica de `app.py` para funções puras chamáveis por um framework HTTP separado — ver
sugestão de refactor em [03_system_design.md](03_system_design.md) e nos comentários de
[app.py](../app.py)).

## Contratos internos (funções que fazem o papel de "API" entre os módulos)

Como não há uma API HTTP, esta seção documenta os pontos de entrada/contrato entre `app.py`,
`auth.py` e `db.py` — o equivalente, neste sistema, a "endpoints" para fins de integração e
teste.

### `auth.py`

| Função | Parâmetros | Retorno | Descrição |
| --- | --- | --- | --- |
| `is_logged_in()` | — | `bool` | Sessão válida em qualquer um dos dois modos de login |
| `get_current_user_email()` | — | `str` | E-mail do usuário autenticado; levanta `RuntimeError` se chamado sem sessão |
| `render_landing_page()` | — | — | Renderiza a landing page + formulários de login/cadastro |
| `render_user_badge()` | — | — | Renderiza badge do usuário + botão de logout na sidebar |

### `db.py`

| Função | Parâmetros | Retorno | Descrição |
| --- | --- | --- | --- |
| `init_db()` | — | — | Cria as tabelas `users`/`user_credentials` se não existirem |
| `create_user(email, password)` | `str, str` | `bool` | `False` se o e-mail já existe |
| `verify_user(email, password)` | `str, str` | `bool` | Confere e-mail/senha contra o hash salvo |
| `get_credentials(email)` | `str` | `dict \| None` | Credencial GEE decifrada, ou `None` (não cadastrada **ou** corrompida — ver [04_database.md](04_database.md)) |
| `save_credentials(email, credentials)` | `str, dict` | — | Cifra e persiste (upsert) |

### `app.py` (funções de domínio, testáveis isoladamente da UI)

| Função | Parâmetros | Retorno | Descrição |
| --- | --- | --- | --- |
| `validate_file_upload(uploaded_file, allowed_extensions=None, max_size=None)` | arquivo Streamlit, `set`, `int` | `(bool, str)` | Valida tamanho, extensão e nome do arquivo |
| `initialize_ee(credentials)` | `dict` | `bool` | Inicializa o SDK do Earth Engine com a credencial do usuário |
| `save_gee_credentials_from_json(user_email, json_input)` | `str, str` | `bool` | Valida estrutura do JSON e delega a `db.save_credentials` |
| `uploaded_file_to_gdf(data)` | arquivo Streamlit | `GeoDataFrame` | Converte GeoJSON enviado em GeoDataFrame |
| `extract_landscape_from_tif(uploaded_tif, point_lonlat, buffer_dist, on_progress=None)` | arquivo, `(lon, lat)`, `float`, `callable` | `(np.ndarray, (float, float))` | Recorta GeoTIFF próprio na área do buffer |

Essas assinaturas são a base recomendada para os testes automatizados descritos em
[13_testing.md](13_testing.md) — são funções relativamente puras (sem depender do ciclo de
render do Streamlit), diferente do restante do corpo de `app.py`.
