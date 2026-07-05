import { test, expect } from "@playwright/test";

// Smoke test do fluxo de login/cadastro (auth.py). Não cobre o pipeline de
// métricas (exige uma credencial real do Earth Engine — fora de escopo de
// CI, ver documentation/13_testing.md). Objetivo: garantir que a landing
// page carrega e que a validação de cadastro por e-mail/senha funciona
// fim-a-fim contra uma instância real do Streamlit (não apenas a função
// isolada, já coberta em tests/test_auth.py).
//
// Streamlit não desmonta o conteúdo de abas inativas (st.tabs) — ambos os
// formulários ("Entrar" e "Criar conta") continuam no DOM, só ocultos
// visualmente. Por isso cada teste escopa a busca de campos ao tabpanel
// visível no momento (.filter({ visible: true })), em vez de usar
// page.getByLabel(...) direto, que bateria nos dois formulários ao mesmo
// tempo (erro de "strict mode violation" descoberto rodando este teste
// contra o app real).

test.describe("Landing page e cadastro", () => {
  test("mostra a landing page para um visitante não autenticado", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Landscape Metrics Extractor")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Entrar" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Criar conta" })).toBeVisible();
  });

  test("rejeita cadastro com e-mail inválido", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: "Criar conta" }).click();
    const panel = page.getByRole("tabpanel").filter({ visible: true });

    await panel.getByLabel("E-mail", { exact: true }).fill("nao-e-um-email");
    await panel.getByLabel("Senha", { exact: true }).fill("senha12345");
    await panel.getByLabel("Confirmar senha").fill("senha12345");
    await panel.getByRole("button", { name: "Criar conta" }).click();

    await expect(page.getByText("Informe um e-mail válido")).toBeVisible();
  });

  test("rejeita cadastro com senha curta", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: "Criar conta" }).click();
    const panel = page.getByRole("tabpanel").filter({ visible: true });

    await panel.getByLabel("E-mail", { exact: true }).fill("novo.usuario@example.com");
    await panel.getByLabel("Senha", { exact: true }).fill("123");
    await panel.getByLabel("Confirmar senha").fill("123");
    await panel.getByRole("button", { name: "Criar conta" }).click();

    await expect(page.getByText("pelo menos 8 caracteres")).toBeVisible();
  });

  test("rejeita login com credenciais incorretas", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: "Entrar" }).click();
    const panel = page.getByRole("tabpanel").filter({ visible: true });

    await panel.getByLabel("E-mail", { exact: true }).fill("ninguem@example.com");
    await panel.getByLabel("Senha", { exact: true }).fill("senha-errada");
    await panel.getByRole("button", { name: "Entrar" }).click();

    await expect(page.getByText("E-mail ou senha inválidos")).toBeVisible();
  });
});
