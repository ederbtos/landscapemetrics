# 18. Acessibilidade Digital e Inclusão

Este documento estabelece as diretrizes e a implementação de acessibilidade para o **Landscape Metrics Extractor**, em conformidade com WCAG 2.2 AA, eMAG e a Lei Brasileira de Inclusão (LBI). A acessibilidade é tratada como requisito estrutural, não opcional.

## 🎯 Objetivos de Acessibilidade
- Garantir acesso completo a pessoas com deficiência (motora, visual, auditiva e cognitiva).
- Garantir navegação 100% via teclado e leitores de tela (NVDA, JAWS, VoiceOver).
- Integrar tradução para LIBRAS (Avatar Maria Júlia & Pedro).

## 👁️ Acessibilidade Visual
- **Alto Contraste:** A paleta de cores (ex: `#2a78d6` nos gráficos) foi validada para garantir taxa de contraste mínima de 4.5:1 para textos normais.
- **Foco Visível:** Todos os elementos interativos possuem `:focus-visible` definido claramente no CSS para navegação por teclado.
- **Leitores de Tela:** Uso de HTML5 semântico (`<main>`, `<nav>`, `<section>`) e atributos `aria-label` e `aria-describedby` nas dicas contextuais `.chart-help`.

## 🧏 Acessibilidade para Deficiência Auditiva (LIBRAS)
- A plataforma conta com suporte planejado para VLibras e integração com Avatares 3D customizados (Maria Júlia e Pedro).
- Todo conteúdo em áudio ou vídeo (caso exista no onboarding) possui legendas (`<track>`) e transcrição em texto.
- Alertas de sucesso e erro na UI (ex: falha de extração do MapBiomas) são visuais, não dependendo de notificações sonoras.

## ✋ Acessibilidade Motora
- Navegação completa por teclado. Ausência de "keyboard traps".
- O mapa interativo (Leaflet) pode ser contornado via teclado.
- As áreas de clique (touch targets) possuem no mínimo 44x44 CSS pixels para facilitar o uso no PWA (Mobile).

## 🧠 Acessibilidade Cognitiva
- Os termos complexos de ecologia de paisagens (ex: FRAGSTATS, Shannon) possuem tooltips didáticos (ver `19_ux_help_system.md`).
- A jornada (Wizard) é dividida em passos claros e lógicos, sem limite de tempo, evitando sobrecarga cognitiva.
