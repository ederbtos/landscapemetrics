# 09 — Regras de Negócio

## Autenticação e conta

| Regra | Onde é aplicada |
| --- | --- |
| E-mail precisa bater com o padrão `algo@algo.algo` no cadastro | `auth._render_register_form` (`EMAIL_RE`) |
| Senha precisa ter no mínimo 8 caracteres | `auth._render_register_form` |
| Senha e confirmação de senha precisam ser iguais | `auth._render_register_form` |
| Não pode haver duas contas com o mesmo e-mail | `db.create_user` (constraint `PRIMARY KEY`) |
| Senha nunca é armazenada em texto puro (hash bcrypt) | `db.create_user` / `db.verify_user` |
| Sessão de login por senha expira em 24h (JWT `exp`) | `auth.JWT_EXPIRATION` |
| E-mail não é verificado em nenhum dos dois modos de login | Documentado em `auth.py` — é uma chave de conta, não prova de posse do endereço |

## Credenciais do Earth Engine

| Regra | Onde é aplicada |
| --- | --- |
| Cadastro de credencial é obrigatório antes de qualquer análise | `app.py`, bloco após `db.get_credentials` |
| JSON precisa ter `client_email`, `private_key` e `project_id` | `app.save_gee_credentials_from_json` |
| Validação é apenas estrutural — credencial "salva com sucesso" não implica "funcional" | Documentado em `app.py`; falha real só aparece em `initialize_ee` |
| Uma nova credencial sempre substitui a anterior (sem histórico) | `db.save_credentials` (upsert por e-mail) |
| Earth Engine é inicializado via endpoint `earthengine-highvolume` | `app.initialize_ee` |

## Upload de arquivos

| Regra | Onde é aplicada |
| --- | --- |
| GeoJSON: apenas `.geojson`, até 10 MB (`MAX_FILE_SIZE`) | `app.validate_file_upload` |
| GeoTIFF: apenas `.tif`/`.tiff`, até 5 GB (`MAX_TIF_SIZE`) | `app.validate_file_upload` (chamado com `ALLOWED_TIF_EXTENSIONS`) |
| Nome do arquivo não pode conter `.. / \ < > \| * ?` (defesa contra path traversal) | `app.validate_file_upload` |
| Arquivo é sempre salvo com nome gerado por `uuid4`, nunca com o nome original | `app.uploaded_file_to_gdf` / `app.extract_landscape_from_tif` |
| Arquivo temporário é sempre removido após o uso, com sucesso ou falha | Bloco `finally` em ambas as funções |
| `server.maxUploadSize` (Streamlit) precisa bater com `MAX_TIF_SIZE` | `.streamlit/config.toml` (5120 MB = 5 GB) |

## Seleção do ponto e buffer

| Regra | Onde é aplicada |
| --- | --- |
| Exatamente 1 ponto por execução — 0 ou mais de 1 é erro bloqueante | `app.py`, validação de `gdf_features` |
| Buffer entre 1.000 m (`MIN_BUFFER`) e 10.000 m (`MAX_BUFFER`) | Slider em `app.py` |
| GeoTIFF próprio precisa ter CRS projetado (metros), não geográfico (graus) | `app.extract_landscape_from_tif` |
| Mínimo de 9 pixels válidos (`MIN_VALID_PIXELS`) para formar uma matriz 3×3 mínima via `reduceRegion` | `app.py`, fallback do MapBiomas |
| Se a área recortada não tiver nenhum pixel válido (todos `nodata`), a extração falha explicitamente | `app.extract_landscape_from_tif` |

## Regra central: integridade dos dados exibidos

> **Nenhuma métrica é exibida ou exportada sem dados reais por trás.** Se a extração de pixels
> falhar em qualquer estágio (MapBiomas/Earth Engine ou GeoTIFF próprio), o processamento é
> interrompido (exceção propagada → `st.stop()`) com uma mensagem explicando a causa provável.

Isso substitui um comportamento anterior, removido deliberadamente, em que uma falha de extração
era mascarada por uma matriz de exemplo fixa ("dados representativos de Santa Catarina") — ver
histórico do projeto e a seção "Melhorias sugeridas" nos docstrings de `app.py`.

## Cálculo e exibição de métricas

| Regra | Onde é aplicada |
| --- | --- |
| Se a área tiver menos de 3×3 pixels, é expandida com padding antes do PyLandStats | `app.py`, antes de `pls.Landscape` |
| Tabela de resultados mostra apenas classes com proporção de paisagem > 10% | `app.py` — se nenhuma classe ultrapassar, mostra todas |
| Legenda de classes é fixa por posição de índice (esquema aproximado da Collection 9) | `app.py`, `legend_keys` — limitação conhecida se uma collection futura mudar códigos |
| CSV exportado usa separador `;` e decimal `,` (formato pt-BR) | `app.convert_df` |
