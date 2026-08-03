import { test, expect } from '@playwright/test';

test.describe('Autenticação e Acesso à Plataforma', () => {

  test('Deve carregar a Landing Page com sucesso', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Landscape Metrics Extractor/);
    const heroText = page.locator('text=Entenda padrões de paisagem');
    await expect(heroText).toBeVisible();
  });

  test('Não deve acessar a plataforma sem login (redirecionamento silencioso)', async ({ page }) => {
    await page.goto('/index.html');
    // Verifica se o modal de login abre automaticamente, ou se tem o botão de Entrar/Cadastrar
    const loginButton = page.locator('#btn-open-login');
    await expect(loginButton).toBeVisible();
    
    // Verifica se o app-shell principal está oculto, pois não está autenticado
    const appShell = page.locator('#app-shell');
    await expect(appShell).toBeHidden();
  });

  test('Fluxo de login de teste (Simulação)', async ({ page }) => {
    await page.goto('/index.html');
    
    // Abre o modal de login
    await page.click('#btn-open-login');
    
    // Se estivesse no ambiente de testes com banco, preencheríamos aqui
    // await page.fill('input[type="email"]', 'test@test.com');
    // await page.fill('input[type="password"]', 'password123');
    // await page.click('button:has-text("Entrar")');
    
    // Como é E2E puro, validaremos apenas se o modal abriu corretamente
    const authModal = page.locator('#auth-modal');
    await expect(authModal).toBeVisible();
  });

});
