# 21. Validação de Sessão Padrão de Mercado & PWA

Este documento documenta a arquitetura de Autenticação e Configuração de Progressive Web App (PWA) para mobile.

## 🔐 1. Validação de Sessão (JWT + Refresh Token)
No ecossistema atual (FastAPI + TypeScript Estático), a melhor abordagem recomendada de mercado é o uso de **Access Token e Refresh Token armazenados em Cookies HttpOnly** para mitigar ataques XSS.

- **Access Token:** Duração de 15 minutos. Usado nas chamadas à API via cabeçalho `Authorization: Bearer` (ou lido via HttpOnly se no mesmo domínio).
- **Refresh Token:** Duração de 7 dias, armazenado exclusivamente em cookie HttpOnly com as flags `Secure` e `SameSite=Strict`.
- **Silent Refresh:** O frontend tenta fazer uma chamada para `/api/auth/refresh` antes da expiração do Access Token, recebendo um novo JWT transparente para o usuário.
- **Logout (Blacklist):** O endpoint `/api/auth/logout` limpa os cookies e invalida a string do Refresh Token ativa no banco de dados.

## 📱 2. Configuração PWA (Foco Mobile)
O sistema conta com suporte a PWA, permitindo instalação nativa e cache offline parcial via Service Worker.

### 📄 Manifest (`static/manifest.json`)
```json
{
  "name": "Landscape Metrics Extractor",
  "short_name": "LandscapeApp",
  "description": "Extração e análise de métricas ecológicas",
  "start_url": "/index.html",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#2a78d6",
  "icons": [
    {
      "src": "/icons/icon-192x192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icons/icon-512x512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

### ⚙️ Service Worker (`static/sw.js`)
Configurado para **Cache-First** em assets estáticos (CSS, JS, Imagens) e **Network-First** para chamadas de API.
O frontend (`app.ts`) registra o service worker e escuta o evento `beforeinstallprompt` para disparar um botão personalizado "Instalar Aplicativo" quando o usuário acessa a plataforma em ambiente mobile.
