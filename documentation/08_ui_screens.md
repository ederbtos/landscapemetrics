# 08 — Telas da Aplicação

O app é tecnicamente uma única página Streamlit, mas se comporta como duas "telas" lógicas
dependendo do estado de autenticação/cadastro, mais uma tela intermediária de credenciais.

## Tela 1 — Landing page (`auth.render_landing_page`)

**Quando aparece**: usuário não autenticado.

**Objetivo**: apresentar o app e oferecer login/cadastro.

**Conteúdo**:
- Título, subtítulo e descrição do app.
- Aviso: "Cada usuário usa sua própria conta de serviço do Google Earth Engine."
- Botão "Entrar com Google" (só se `[auth]` estiver configurado em `secrets.toml`).
- Abas "Entrar" / "Criar conta" com formulários de e-mail/senha.

**Ações disponíveis**:
- Login com Google (opcional).
- Login por e-mail/senha.
- Criar conta nova (e-mail + senha + confirmação de senha).

## Tela 2 — Cadastro/atualização de credenciais do Earth Engine

**Quando aparece**: usuário autenticado, mas sem credencial GEE salva (bloqueante) — ou, como
seção opcional (expander), para quem já tem credencial e quer trocá-la.

**Objetivo**: capturar o JSON da conta de serviço do Earth Engine do próprio usuário.

**Ações disponíveis**:
- Colar o JSON da credencial num `text_area`.
- Submeter — validação estrutural imediata, com mensagem de erro se campos obrigatórios
  estiverem ausentes.

## Tela 3 — Tela principal de análise (`app.py`, corpo principal)

**Quando aparece**: usuário autenticado, com credencial GEE salva e Earth Engine inicializado com
sucesso.

**Objetivo**: conduzir o usuário pelas 5 etapas do pipeline de extração de métricas.

**Seções, em ordem**:

| Seção | Título na UI | Ações disponíveis |
| --- | --- | --- |
| Sidebar | 🔒 Informações | Ver limites do sistema; botão "Status GEE" |
| 1 | Selecione um ponto de interesse | Desenhar marcador no mapa; exportar GeoJSON |
| 2 | Upload do arquivo GeoJSON | Enviar o GeoJSON exportado |
| 3 | Fonte dos dados de cobertura do solo | Escolher MapBiomas ou GeoTIFF próprio; enviar GeoTIFF se aplicável |
| 4 | Defina o tamanho do raio (m) do buffer | Ajustar slider (1.000–10.000 m) |
| 5 | Calcular métricas | Clicar no botão que dispara o pipeline |
| Resultado | (sem numeração, aparece após o cálculo) | Ver mapa, gráfico, tabela; baixar CSV |
| Rodapé | Detalhamento das métricas / Referências | Consultar significado de cada métrica; ver bibliografia |

**Estados visíveis ao usuário durante o pipeline** (dentro do `st.status`):
- Preparando área de interesse.
- Conectando/testando assets do MapBiomas (ou recortando o GeoTIFF).
- Calculando métricas no PyLandStats.
- Sucesso (✅) ou erro com detalhamento expansível (🔍).

## Elementos persistentes (em qualquer tela autenticada)

- **Badge do usuário** na sidebar (`auth.render_user_badge`): e-mail do usuário logado + botão
  "Sair".
