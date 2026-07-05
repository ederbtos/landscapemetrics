# Testes

Ver a estratégia completa em [../documentation/13_testing.md](../documentation/13_testing.md).
Resumo rápido:

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

| Arquivo | Cobre |
| --- | --- |
| `test_db.py` | `db.py` — CRUD de usuários e credenciais criptografadas |
| `test_auth.py` | `auth.py` — JWT de sessão, validação de e-mail |
| `test_app_validation.py` | `app.py` — validação de upload, conversão de GeoJSON |
| `test_app_tif.py` | `app.py` — recorte de GeoTIFF próprio (`extract_landscape_from_tif`) |
| `e2e/` | Smoke test Playwright do fluxo de login, contra o app real (ver `e2e/README.md`) |

`conftest.py` e `helpers.py` contêm fixtures/dublês compartilhados — em particular, um dublê de
upload do Streamlit (`FakeUploadedFile`) e um gerador de GeoTIFF sintético em memória
(`make_test_tif`), para não depender de arquivos de teste versionados no repositório.

## Nada aqui depende do Google Earth Engine

Por design: testar contra o Earth Engine real exigiria uma credencial de conta de serviço como
segredo de CI e consumiria cota real a cada execução. Os testes cobrem tudo que é testável sem
essa dependência — validação, persistência, criptografia, sessão e a fonte de dados alternativa
(GeoTIFF próprio, que roda inteiramente local). O caminho MapBiomas/Earth Engine
(`app.py`, dentro de `main()`) permanece coberto apenas por teste manual (ver checklist em
[../documentation/15_dev_guide.md](../documentation/15_dev_guide.md#antes-de-abrir-um-pr)).
