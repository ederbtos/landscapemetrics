import { defineConfig } from "@playwright/test";

// Smoke test contra uma instância local do app já rodando (ver README.md
// deste diretório). Não sobe o Streamlit automaticamente: subir um app
// Streamlit real depende de credenciais/segredos configurados, o que é
// responsabilidade de quem roda os testes localmente ou do workflow de CI
// que optar por incluir este passo (ver documentation/13_testing.md).
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: process.env.APP_BASE_URL || "http://localhost:8501",
    trace: "retain-on-failure",
  },
});
