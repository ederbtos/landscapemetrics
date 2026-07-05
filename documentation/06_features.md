# 06 — Funcionalidades

## 1. Autenticação

- **Login por e-mail/senha** (sempre disponível): cadastro aberto, sem confirmação de e-mail.
  Senha com mínimo de 8 caracteres, comparação de confirmação de senha no cadastro.
- **Login com Google** (opcional): aparece apenas se `.streamlit/secrets.toml` tiver a seção
  `[auth]` configurada com credencial OAuth real. Usa `st.login()` nativo do Streamlit.
- **Logout**: botão na sidebar, disponível independentemente do modo de login usado.

## 2. Gestão de credenciais do Earth Engine

- **Cadastro inicial obrigatório**: usuário sem credencial salva vê um formulário bloqueante antes
  de acessar qualquer funcionalidade de análise.
- **Atualização a qualquer momento**: expander "🔑 Atualizar credenciais do Earth Engine" permite
  substituir a credencial ativa.
- **Validação estrutural**: antes de salvar, confere presença de `client_email`, `private_key` e
  `project_id` no JSON informado (não valida se a credencial funciona — isso só é detectado na
  inicialização do Earth Engine).

## 3. Seleção do ponto de interesse

- Mapa interativo (`geemap`/`folium`) centrado no Brasil, com ferramenta de desenho de marcador e
  exportação para GeoJSON.
- Upload do GeoJSON exportado (até 10 MB, apenas `.geojson`).
- Validação de que o arquivo contém exatamente **um** ponto — mais de um ou nenhum ponto é
  rejeitado com mensagem explícita.
- Fallback de mapa alternativo (folium puro) se o mapa principal do geemap falhar ao carregar.

## 4. Fonte dos dados de cobertura do solo

Escolha explícita entre duas fontes, mutuamente exclusivas por execução:

| Fonte | Como funciona |
| --- | --- |
| **MapBiomas (Google Earth Engine)** | Tenta assets da Collection 9 e recua para 8/7/6 conforme disponibilidade; usa o ano mais recente disponível na collection escolhida |
| **GeoTIFF próprio** | Upload de raster até 5 GB, CRS projetado (metros) obrigatório, recortado localmente pelo buffer definido |

## 5. Configuração do buffer

Slider de raio entre 1.000 m e 10.000 m (passo de 500 m) ao redor do ponto selecionado, definindo
a área circular de análise.

## 6. Cálculo de métricas

- Disparado por um botão explícito ("Calcular métricas"), não automaticamente a cada interação.
- Execução dentro de um `st.status` expansível, com progresso visível por etapa (preparo da área,
  conexão com a fonte de dados, cálculo no PyLandStats).
- 12+ métricas por classe de cobertura do solo (ver lista completa em
  [09_business_rules.md](09_business_rules.md) e no expander "Detalhamento das métricas" do
  próprio app).
- Resultado persistido em `st.session_state` — sobrevive a reruns causados por outros widgets
  (ex.: o botão de download) sem repetir chamadas ao Earth Engine.

## 7. Visualização dos resultados

- Mapa da área de interesse (ponto + buffer) sobre imagem de satélite.
- Gráfico das classes de cobertura do solo dentro do buffer (`ls.plot_landscape`).
- Tabela das classes com proporção de paisagem acima de 10% (todas as classes, se nenhuma
  ultrapassar esse limiar).

## 8. Exportação

- Download da tabela de métricas em CSV (separador `;`, decimal `,` — formato pt-BR), com nome de
  arquivo timestampado.

## 9. Informações de apoio

- Sidebar com limites do sistema (tamanho máximo de arquivo, buffer mínimo/máximo).
- Botão "Status GEE" para checar conectividade com o Earth Engine a qualquer momento.
- Expander com o detalhamento/tradução de cada métrica calculada.
- Seção de referências bibliográficas (PyLandStats, MapBiomas, geemap).
