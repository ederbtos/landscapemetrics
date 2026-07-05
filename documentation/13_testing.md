# 13 — Testes

## Estado atual

**Não há testes automatizados no repositório hoje.** Este documento descreve a estratégia adotada
a partir desta iteração (ver `tests/` na raiz do projeto) e como executá-la.

## Estratégia

Dado que o sistema é um script Streamlit de página única, sem API REST e sem múltiplas entidades
de CRUD (ver [02_architecture.md](02_architecture.md) e [05_api.md](05_api.md)), a estratégia é
dimensionada ao tamanho real do sistema — não replica uma pirâmide de testes de uma aplicação
multi-serviço.

| Tipo | Ferramenta | Escopo |
| --- | --- | --- |
| Unitário | `pytest` | Funções puras/isoláveis: `db.py` (CRUD de usuários e credenciais), `auth.py` (JWT, validação de e-mail), `app.py` (`validate_file_upload`, `uploaded_file_to_gdf`, `extract_landscape_from_tif`) |
| Integração | `pytest` + SQLite temporário | Fluxo completo de `db.py` contra um banco real (arquivo temporário), sem mocks do SQLite |
| E2E (smoke) | `Playwright` | Sobe o app real (`streamlit run`) e valida o fluxo de login → cadastro de credencial inválida → mensagem de erro, contra uma instância local |
| CI | GitHub Actions | Roda os testes unitários/integração a cada push/PR |

Testes que dependem do Google Earth Engine (rede externa + credencial real) **não** são
executados em CI — são isolados e pulados por padrão (ver `tests/README.md`), porque:
1. Exigiriam uma credencial de conta de serviço real armazenada como segredo de CI.
2. Consumiriam cota real do Earth Engine a cada execução.
3. Ferem a regra de negócio central do sistema (nunca fabricar dados) se fossem mockados de forma
   a esconder isso do restante da suíte.

## Estrutura de diretórios

```
tests/
├── conftest.py              # fixtures: banco SQLite temporário, secrets de teste, fix de PROJ_LIB
├── helpers.py                # dublê de upload do Streamlit + gerador de GeoTIFF sintético
├── test_db.py                # CRUD de usuários e credenciais (db.py)
├── test_auth.py               # criação/validação de JWT, regex de e-mail (auth.py)
├── test_app_validation.py     # validate_file_upload, uploaded_file_to_gdf (app.py)
├── test_app_tif.py            # extract_landscape_from_tif com GeoTIFFs sintéticos gerados em memória
└── e2e/
    ├── login-flow.spec.ts      # Playwright: landing page → cadastro/login → mensagens de erro
    ├── playwright.config.ts
    ├── package.json
    └── README.md               # como rodar contra uma instância local do app
```

> **Pré-requisito para `import app` funcionar em teste**: `app.py` foi reestruturado para envolver
> o corpo do script (login, pipeline, UI) em uma função `main()`, chamada só sob
> `if __name__ == "__main__":`. Sob `streamlit run app.py` o comportamento é idêntico a antes;
> a mudança existe só para que `import app` num processo pytest não dispare a aplicação inteira
> (o que antes travava com `RuntimeError` fora de um `ScriptRunContext` real do Streamlit).

## Cobertura por entidade/função

| Componente | Casos cobertos |
| --- | --- |
| `db.create_user` | Sucesso; e-mail duplicado retorna `False` |
| `db.verify_user` | Senha correta; senha incorreta; usuário inexistente |
| `db.save_credentials` / `get_credentials` | Roundtrip cifra/decifra; upsert substitui credencial anterior; e-mail sem credencial retorna `None` |
| `auth._create_token` / `_decode_token` | Token válido decodifica para o e-mail correto; token expirado/adulterado retorna `None` |
| `auth.EMAIL_RE` | E-mails válidos aceitos; formatos inválidos rejeitados |
| `app.validate_file_upload` | Tamanho acima do limite; extensão não permitida; nome com caracteres de path traversal; arquivo válido |
| `app.uploaded_file_to_gdf` | GeoJSON válido com 1 ponto; GeoJSON vazio (erro) |
| `app.extract_landscape_from_tif` | CRS geográfico rejeitado; buffer fora da área do raster rejeitado; recorte válido retorna array e resolução corretos |

## Executando localmente

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

Para os testes E2E (opcionais, exigem Node.js e o app rodando):

```bash
npm --prefix tests/e2e install
npx --prefix tests/e2e playwright install --with-deps chromium
streamlit run app.py &   # instância local para o Playwright testar
npx --prefix tests/e2e playwright test
```

## CI/CD

Workflow em `.github/workflows/tests.yml`: roda `pytest tests/ -m "not e2e"` a cada push/PR contra
`main`, usando um `.streamlit/secrets.toml` de teste gerado no próprio workflow (chaves
aleatórias, nunca reais). Ver [14_deployment.md](14_deployment.md) para a relação entre esse
workflow e o processo de deploy (são independentes: CI valida o código, deploy é manual via
`scripts/deploy.sh`).

## Fora de escopo (deliberadamente)

- Testes de carga/performance contra o Earth Engine.
- Testes de UI pixel-a-pixel dos mapas Folium/geemap (renderização de mapa não é asserção estável
  o suficiente para CI).
- Qualquer suíte que "funcione" fabricando dados de paisagem falsos para simular o Earth Engine de
  forma indistinguível do real — contrariaria a regra de negócio central do sistema (ver
  [09_business_rules.md](09_business_rules.md)).
