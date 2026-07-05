# E2E (Playwright) — smoke test do fluxo de login

Cobre apenas o fluxo de login/cadastro (`auth.py`) contra uma instância **real** do Streamlit —
não cobre o pipeline de métricas, que exige uma credencial real do Google Earth Engine (fora de
escopo de CI, ver [../../documentation/13_testing.md](../../documentation/13_testing.md)).

## Rodando localmente

```bash
# 1. Instalar dependências do teste (uma vez)
npm --prefix tests/e2e install
npx --prefix tests/e2e playwright install --with-deps chromium

# 2. Subir o app numa instância local (em outro terminal)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # se ainda não existir
# edite jwt_secret_key e app_encryption_key
streamlit run app.py --server.port 8501

# 3. Rodar os testes contra essa instância
npx --prefix tests/e2e playwright test
```

Por padrão os testes apontam para `http://localhost:8501`. Para apontar para outra porta/host:

```bash
APP_BASE_URL=http://localhost:8599 npx --prefix tests/e2e playwright test
```

## Por que não roda automaticamente no CI

O workflow em `.github/workflows/tests.yml` roda apenas a suíte `pytest` (unitária/integração).
Rodar o Playwright em CI exigiria subir o Streamlit real dentro do runner (com um
`secrets.toml` de teste, já gerado nesse workflow) e aguardar o boot antes de testar — factível,
mas deixado de fora por ora para manter o CI rápido e focado na lógica de negócio. Se quiser
habilitar, adicione um passo que suba `streamlit run app.py &`, aguarde o healthcheck
(`/_stcore/health`) responder e então rode `npx --prefix tests/e2e playwright test`.

## Nota sobre `st.tabs`

O Streamlit não desmonta o conteúdo de abas inativas — os campos das abas "Entrar" e "Criar
conta" continuam ambos no DOM, só ocultos visualmente. Por isso os testes escopam a busca de
campos ao `tabpanel` visível (`page.getByRole("tabpanel").filter({ visible: true })`) em vez de
`page.getByLabel(...)` direto — do contrário o Playwright falha com "strict mode violation" por
encontrar dois campos com o mesmo rótulo.
