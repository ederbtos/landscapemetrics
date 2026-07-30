# Roadmap — Landscape Metrics Extractor

## Progresso geral: ~95%

| Fase | Descrição | Status | % |
| --- | --- | --- | --- |
| 1 | Landing page | ✅ Concluída | 100% |
| 2 | Login (e-mail/senha + JWT, com Google OAuth opcional) | ✅ Concluída | 100% |
| 3 | Credenciais por usuário | ✅ Concluída | 100% |
| 4 | Deploy (HTTPS, Docker Compose, Caddy) | ✅ Concluída | 100% |
| 5 | Motor de métricas de paisagem | ✅ Concluída | 100% |
| 6 | Área municipal (IBGE), matriz socioecológica (SSE), predição de anos futuros (Markov) e lote por município via shapefile | ✅ Concluída | 100% |
| 7 | Agrupamento Multivariado K-Means & DBSCAN com PCA 2D e curva do cotovelo | ✅ Concluída | 100% |
| 8 | Suporte a Banco de Dados PostgreSQL & Escritório Virtual com isolamento por usuário | ✅ Concluída | 100% |
| 9 | PWA Mobile, Governança LGPD, Defesa em Profundidade de IA, Acessibilidade WCAG/VLibras e Avatares 3D (Maria Júlia & Pedro) | ✅ Concluída | 100% |
| 10 | Dados de referência nacionais pré-carregados no banco (malha municipal IBGE, MapBiomas agregado, PRODES, ANA) | 🔧 Em andamento | ~95% |

> A Fase 10 (2026-07-26, dados concluídos em 2026-07-27) cobre a pré-carga de dados nacionais de
> referência no banco do backend FastAPI — ver detalhamento abaixo. Malha municipal (5.570
> municípios), PRODES (3,94M registros, 6 biomas) e MapBiomas (540/540 UF×ano, 2004–2023) estão
> 100% concluídos; só falta ANA, bloqueada por credencial (ação do operador, não de código).


## Status atual (2026-07-04)

### ✅ Concluído

- **Dependências corrigidas**: `requirements.txt` tinha pins incompatíveis com ambientes atuais
  (`pylandstats==3.0.0` não tem wheel para Windows/Python 3.13; `geemap==0.30.0` quebra com
  `setuptools>=81` e `ipython>=9`). Ajustado para `pylandstats==3.1.0`, `setuptools<81`, `ipython<9`.
- **Dockerfile**: imagem baseada em `python:3.11-slim`, com `libexpat1`/`libgomp1` (dependências
  nativas do rasterio/GDAL) e healthcheck em `/_stcore/health`.
- **docker-compose.yml**: sobe o app expondo a porta 8501 e montando `.streamlit/secrets.toml`
  como volume somente-leitura (as credenciais nunca vão para dentro da imagem).
- **`.streamlit/secrets.toml.example`**: modelo do arquivo de segredos do app (`jwt_secret_key`
  para assinar a sessão de login, seção `[auth]` opcional para o Google OAuth e
  `app_encryption_key` para cifrar as credenciais salvas) — não contém a credencial de conta de
  serviço do Earth Engine, que é por usuário (Fase 3).
- **Fase 1 — Landing page** ([auth.py](auth.py)): tela inicial explicando o app antes do login,
  como primeira renderização do próprio `app.py` (sem app multi-página) quando o usuário ainda
  não está autenticado.
- **Fase 2 — Login, dois modos** ([auth.py](auth.py), [db.py](db.py)):
  - **E-mail/senha (sempre disponível)**: cadastro aberto, senha nunca em texto puro — só o hash
    bcrypt na tabela `users` de `data/app.db`. Sessão representada por um JWT (HS256, assinado com
    `jwt_secret_key`) guardado em `st.session_state` — não sobrevive a um refresh (F5) da página,
    já que não é persistido em cookie.
  - **Google OAuth (opcional)**: aparece como botão extra na landing page quando a seção `[auth]`
    de `secrets.toml` está preenchida com uma credencial OAuth real do Google Cloud Console. Usa
    `st.login()`/`st.user`/`st.logout()` nativos do Streamlit; a sessão sobrevive a um refresh
    (cookie assinado pelo próprio Streamlit), ao contrário do modo e-mail/senha.
  - Os dois modos compartilham o e-mail como chave de identidade em `data/app.db` — ver
    `get_current_user_email()`. Badge do usuário e botão de logout na sidebar (independente do
    modo usado) em [app.py](app.py) linha 283.
- **Fase 3 — Credenciais por usuário** ([db.py](db.py), [app.py](app.py) linhas 285-297): cada
  usuário cola o JSON da própria conta de serviço do Earth Engine, que é criptografado com Fernet
  (`app_encryption_key` em `secrets.toml`) e persistido em SQLite (`data/app.db`), com formulário
  de atualização das credenciais a qualquer momento.
- **Remoção dos dados de fallback sintéticos** ([app.py](app.py)): quando a extração de pixels do
  MapBiomas/Earth Engine falhava, o app anteriormente substituía os dados por uma matriz fixa
  fictícia ("Santa Catarina") e seguia calculando métricas/CSV como se fossem reais. Agora, uma
  falha na extração real interrompe o processamento (`st.stop()`) com uma mensagem explicando a
  causa provável — nenhuma métrica é exibida ou exportada sem dados reais por trás.
- **Fonte de dados alternativa: GeoTIFF próprio** ([app.py](app.py), função
  `extract_landscape_from_tif`): além do MapBiomas via Earth Engine, o usuário pode escolher
  ("3) Fonte dos dados de cobertura do solo") enviar seu próprio raster GeoTIFF (até 5GB — ver
  `MAX_TIF_SIZE` e `.streamlit/config.toml`/`server.maxUploadSize`). O ponto e o buffer definidos
  na interface recortam esse raster localmente via `rasterio`/`pyproj`/`shapely` (o raster pode
  cobrir uma área bem maior que o buffer). Exige CRS projetado (metros) — rejeitado explicitamente
  se for geográfico (graus), já que o buffer é definido em metros — e assume os mesmos códigos de
  classe do MapBiomas (a legenda usada no restante do app não muda). A resolução real do pixel é
  lida do próprio raster (em vez do valor fixo de 30m usado no caminho MapBiomas/GEE) e passada a
  `pls.Landscape`. Segue a mesma regra de "falhar explicitamente" das demais fontes: sem pixels
  válidos no buffer, o processamento para (`st.stop()`) em vez de gerar uma métrica a partir de
  dados incompletos.
- **Botão "Calcular métricas" + pipeline em tempo real** ([app.py](app.py)): o cálculo deixou de
  rodar automaticamente a cada interação do Streamlit (o que reprocessaria tudo — inclusive
  uploads grandes de GeoTIFF — a cada rerun) e passou a ser disparado por um botão explícito.
  Dentro de `st.status(..., expanded=True)`, cada etapa (preparar área de interesse, conectar ao
  MapBiomas ou recortar o GeoTIFF, calcular métricas no PyLandStats) aparece em tempo real com seu
  próprio ícone de andamento/concluído/erro. O resultado (array de classes, `Landscape` do
  PyLandStats, tabela de métricas, geometrias do buffer) é guardado em `st.session_state` para
  sobreviver a reruns causados por outros widgets (ex.: o botão de download do CSV) sem precisar
  refazer chamadas ao Earth Engine ou reprocessar o GeoTIFF.
- **Preparação da Fase 4 (deploy)**: [docker-compose.prod.yml](docker-compose.prod.yml) sobe o app
  atrás de um proxy reverso [Caddy](https://caddyserver.com/) que emite e renova HTTPS
  automaticamente via Let's Encrypt, genérico para qualquer VPS com Docker (não amarrado a um
  provedor específico). Modelo de configuração em
  [Caddyfile.example](Caddyfile.example).
- **Deploy em um comando**: [scripts/deploy.sh](scripts/deploy.sh) automatiza tudo que não depende
  de uma decisão de infraestrutura — gera o `Caddyfile` a partir do domínio informado e sobe
  `docker-compose.prod.yml`. O que resta é só escolher servidor/domínio (ver "Fase 4 — Deploy"
  abaixo) e rodar `./scripts/deploy.sh seu-dominio.com` no servidor.
- **Backup de `data/app.db`**: [scripts/backup-db.sh](scripts/backup-db.sh) gera dumps datados
  localmente (mantendo os 30 mais recentes) e, se a variável `BACKUP_REMOTE` estiver definida,
  envia via `rsync` para fora do servidor — pronto para agendar via `cron`.
- **Validação end-to-end confirmada pelo usuário (2026-07-04)**: fluxo completo de extração de
  métricas com credencial real do Earth Engine testado com sucesso (login → credenciais →
  seleção de ponto → cálculo de métricas via MapBiomas/GEE).
- **Configuração Docker validada localmente (2026-07-04)**: `secrets.toml` preenchido e stack
  local (`docker-compose.yml`) testada com sucesso — reduz o risco da execução da Fase 4, mas o
  deploy em si (servidor/domínio públicos) ainda não foi feito.
- **Bug crítico corrigido (2026-07-05)**: o bloco que instancia o PyLandStats e marca
  `metrics_ready=True` estava aninhado só no `else` (caminho do GeoTIFF próprio) do `if/else` de
  `data_source` — escolher "MapBiomas (Google Earth Engine)" e clicar em "Calcular métricas"
  extraía os pixels mas nunca calculava nem exibia nada, sem erro visível. Bug pré-existente
  (não introduzido nesta sessão), corrigido em [app.py](app.py) e confirmado pelo usuário testando
  o fluxo real com Earth Engine. Aproveitando a mudança, foi adicionado suporte a shapefile
  compactado em `.zip` como alternativa ao GeoJSON para o ponto de interesse (Seção 2), e um teste
  de regressão estrutural contra o bug de aninhamento.
- **Modo "raster inteiro" para GeoTIFF próprio (2026-07-06)**: até então, mesmo usando "Meu raster
  (GeoTIFF)", o app sempre exigia o upload de um ponto de interesse (Seção 2) para recortar o
  raster por buffer — não havia como calcular métricas para a área inteira de um raster próprio
  sem também enviar um ponto. Agora, se o usuário escolher "Meu raster (GeoTIFF)" e **não** enviar
  um ponto, o app calcula as métricas de paisagem para a extensão inteira do raster enviado (sem
  recorte por ponto/buffer) — `extract_landscape_from_tif` ganhou um modo de leitura completa
  (`point_lonlat`/`buffer_dist` agora opcionais), e a UI mostra um aviso indicando qual modo está
  ativo. O caminho MapBiomas continua sempre exigindo um ponto (é um asset nacional, sem uma
  "extensão inteira" delimitada). Coberto por 3 novos testes em `tests/test_app_tif.py`.
- **Barra de progresso geral do pipeline (2026-07-06)**: antes, só a leitura do GeoTIFF tinha
  indicador de progresso — as demais etapas (preparar ROI, conectar ao MapBiomas, calcular
  métricas) só mostravam mensagens de texto sem indicar quanto faltava. Agora uma única barra
  (`overall_progress`/`_set_stage` em [app.py](app.py)) acompanha o pipeline inteiro do clique em
  "Calcular métricas" até o fim, com etapa + percentual juntos (ex.: "Conectando ao MapBiomas...
  (30%)"), independente da fonte de dados escolhida.
- **Revelação progressiva das métricas (2026-07-06)**: em vez de só "calculando métricas..."
  seguido da tabela inteira de uma vez, cada métrica agora abre em seu próprio expander conforme é
  computada (com um pequeno atraso entre uma e outra), tornando o acompanhamento mais didático —
  o usuário vê o que cada métrica significa junto com o valor, não só uma tabela técnica ao final.
  `METRICS_INFO` centraliza nome/ícone/tradução de cada métrica, reaproveitado também no expander
  "Detalhamento das métricas" do rodapé (antes duplicado em duas listas separadas).
- **Reprojeção automática de GeoTIFF em CRS geográfico (2026-07-06)**: antes, um raster próprio em
  graus (WGS84) era rejeitado com um erro pedindo para o usuário reprojetar manualmente fora do
  app. Agora `extract_landscape_from_tif` reprojeta automaticamente:
  - **Com ponto de interesse**: recorta uma janela (com margem de segurança) ao redor do ponto
    ainda em graus — bem mais barato que reprojetar o raster inteiro — e reprojeta só essa janela
    para a zona UTM que contém o ponto (`_utm_epsg_for_lonlat`).
  - **Modo raster inteiro (sem ponto)**: reprojeta para SIRGAS 2000/Brazil Polyconic (EPSG:5880),
    pensada para minimizar distorção de área na extensão inteira do Brasil. Se o raster tiver mais
    de `WHOLE_RASTER_MAX_PIXELS` (50 milhões), é reamostrado por moda (nunca interpolado — dado é
    categórico) antes da reprojeção, para caber na memória do processo — motivado por um caso real
    de teste com um raster de ~3,66 bilhões de pixels que exigiria dezenas de GB de RAM para o
    PyLandStats calcular patches sem essa redução.
  - A reprojeção sempre usa `Resampling.nearest` (nunca interpola valores de classe). O raster
    final (já recortado/reprojetado) fica disponível para download na seção de resultados
    (`st.download_button`), já que o container Docker não tem acesso ao sistema de arquivos do
    host para salvar o arquivo convertido diretamente em disco.
  - Coberto por novos testes em `tests/test_app_tif.py`, incluindo um teste direto de
    `_utm_epsg_for_lonlat` contra zonas UTM conhecidas.
- **Gráficos por métrica com Altair (2026-07-06)**: a revelação progressiva das métricas (item
  acima) ganhou um gráfico de barras horizontal (Altair, com tooltip) por métrica, além da tabela —
  cor `#2a78d6` validada pela paleta de referência da skill de dataviz do projeto (todos os checks
  de contraste/CVD passam). `_render_metric_chart` em [app.py](app.py).
- **Upload de múltiplos GeoTIFFs com comparação e relatório para impressão (2026-07-07)**: até
  então, "Meu raster (GeoTIFF)" só aceitava um arquivo por vez. Agora o uploader da Seção 3 aceita
  vários arquivos (`accept_multiple_files=True`), funcionando nos dois modos (ponto+buffer ou
  raster inteiro):
  - Cada arquivo passa pelo mesmo pipeline de extração/reprojeção/PyLandStats já existente
    (`extract_landscape_from_tif` + `_compute_class_metrics`, esta última extraída da lógica que
    antes só existia inline no caminho de arquivo único — sem mudança de comportamento nele).
  - O ano de cada arquivo é identificado pelo nome (`_extract_year_from_filename`, regex `19xx`/
    `20xx` — ex.: `Corte_255_2010.tif` → 2010) para ordenar e rotular a comparação como série
    temporal; se algum arquivo não tiver um ano identificável, a ordem de upload é usada.
  - Resultados: um resumo compacto por arquivo (plot + tabela, em `_render_multi_file_results`) e
    uma seção de comparação com um gráfico de linha (matplotlib) por métrica — uma linha por classe
    de cobertura do solo, cor fixa por classe (paleta categórica de 8 slots da skill de dataviz,
    `CATEGORICAL_PALETTE`), limitado às classes de maior área média entre os arquivos.
  - Botão "📥 Baixar relatório (HTML)" (`_build_html_report`) gera um HTML autocontido (tabelas +
    gráficos comparativos embutidos como PNG em base64) para o usuário abrir no navegador e
    imprimir/salvar como PDF (Ctrl+P) — evita adicionar uma biblioteca de geração de PDF nova à
    imagem Docker.
  - MapBiomas continua sempre single-source (não há múltiplos "arquivos" nesse caminho).
  - Coberto por `tests/test_app_metrics.py` (extração de ano, cálculo compartilhado de métricas,
    gráfico de comparação, conteúdo do relatório HTML).
- **Progresso incremental real por métrica (2026-07-07)**: a barra geral do pipeline ficava
  "parada" numa % durante o cálculo de métricas sem indicar o que estava acontecendo — medido via
  benchmark: `euclidean_nearest_neighbor_mn` sozinha responde por ~97% do tempo total (12s de
  12,7s num raster 3000×3000 com patches realistas), enquanto as outras 11 métricas somadas levam
  ~0,4s. `_compute_class_metrics` agora calcula uma métrica por vez (sem custo extra relevante — o
  PyLandStats reaproveita internamente os cálculos de patch já feitos no mesmo objeto `Landscape`
  entre chamadas, confirmado por benchmark: 12,70s separado vs 13,21s numa única chamada), com um
  callback `on_metric_progress` que atualiza a barra métrica a métrica e avisa especificamente
  quando chega na métrica lenta.
- **Métricas de área central e nível de paisagem (2026-07-07)**: comparado ao catálogo oficial do
  FRAGSTATS (Área/Borda, Forma, Área Central, Contraste, Agregação, Diversidade — ver
  [fragstats.org](https://fragstats.org/index.php/background/landscape-metrics)), o app só cobria
  Área/Borda e Forma, tudo em nível de classe. Adicionado:
  - **Área Central (Core Area)**, em `METRICS_INFO`: `patch_density`, `edge_density`,
    `total_core_area`, `core_area_proportion_of_landscape`, `core_area_mn`, `core_area_index_mn`,
    `number_of_disjunct_core_areas`, `disjunct_core_area_mn` — reaproveitam toda a UI genérica já
    existente (revelação progressiva, gráfico, tabela, comparação entre arquivos, relatório HTML),
    já que tudo é dirigido por essa lista.
  - **Diversidade e Agregação em nível de PAISAGEM** (`LANDSCAPE_METRICS_INFO`,
    `_compute_landscape_metrics`, `_render_landscape_metrics`): um valor único por arquivo (não por
    classe), exibido como stat tiles — SHDI, CONTAG, MESH, PD, ED, LSI vêm do PyLandStats
    (`compute_landscape_metrics_df`); SHEI, SIDI, SIEI e Riqueza de Manchas (PR) são calculadas
    manualmente (fórmulas padrão do FRAGSTATS a partir das proporções de área por classe — sem
    método dedicado equivalente no PyLandStats 3.1.0 instalado).
  - **Fora do escopo, documentado explicitamente no app** (expander "Detalhamento das métricas") e
    aqui: Aggregation Index (AI), Clumpiness Index (CLUMPY), Landscape Division Index (DIVISION) e
    Splitting Index (SPLIT) não têm método equivalente no PyLandStats instalado. Interspersion &
    Juxtaposition Index (IJI), Proximity Index e Contiguity Index existem como métodos em
    `pls.Landscape` mas levantam `NotImplementedError` nesta versão — confirmado testando
    diretamente antes de expor qualquer um deles na interface, em vez de assumir pela lista de
    métodos disponíveis. Métricas de Contraste (ex.: TECI) exigiriam uma matriz de similaridade
    entre classes configurada pelo usuário, não suportado pela UI atual.
  - Coberto por novos testes em `tests/test_app_metrics.py` (fórmulas de diversidade manuais
    conferidas contra o cálculo direto, renderização sem exceção).
- **CSV das métricas de paisagem + resumo de onde encontrar resultados (2026-07-07)**: as métricas
  de nível de paisagem (item acima) só apareciam na tela e no relatório HTML (modo multi-arquivo)
  — sem exportação própria no fluxo de arquivo único. Adicionado um segundo botão "📥 Download CSV
  (métricas de paisagem)" ao lado do CSV de métricas por classe já existente. Também adicionada ao
  [README.md](README.md#-onde-encontrar-seus-resultados) uma tabela "📍 Onde encontrar seus
  resultados" consolidando, para cada resultado calculado, onde ele aparece na tela, se persiste
  entre interações (`st.session_state`) e como exportá-lo — antes essa informação estava espalhada
  em várias seções do documento.
- **Ordem das métricas por custo de dependência (2026-07-07)**: `euclidean_nearest_neighbor_mn`
  (a métrica mais lenta, ~12,5s de ~12,7s totais no benchmark — depende da posição de TODOS os
  patches da classe entre si) estava no MEIO de `METRICS_INFO`, obrigando o usuário a esperar por
  ela antes de ver métricas rápidas que vinham depois (as 8 de área central, adicionadas em
  2026-07-07 mais cedo). Reordenado em três blocos, do mais barato ao mais caro: Área/Densidade/
  Forma (quase instantâneas, ~0-0,4s cada) → Área Central (custo próprio moderado, ~0,5-0,7s cada
  — erosão de borda) → Isolamento (`euclidean_nearest_neighbor_mn`, sempre por último). Com isso o
  usuário vê a maioria das métricas quase de imediato, em vez da mais lenta travando o meio da
  revelação progressiva.
- **Arquivos temporários retidos até o lote inteiro terminar, no modo multi-arquivo (2026-07-07)**:
  antes, cada GeoTIFF do lote tinha seu arquivo temporário apagado logo após a própria extração
  (dentro do `finally` de `extract_landscape_from_tif`), mesmo que os outros arquivos do lote ainda
  estivessem sendo processados. `extract_landscape_from_tif` ganhou os parâmetros `cleanup` (padrão
  `True`, comportamento inalterado no caminho de arquivo único/MapBiomas) e `temp_path_out` (lista
  onde o caminho do arquivo é anexado quando `cleanup=False`). O loop de múltiplos arquivos agora
  passa `cleanup=False` e só apaga todos os temporários do lote num único `finally` ao redor do
  loop inteiro, depois que as métricas de TODOS os arquivos (não só a extração) foram calculadas —
  inclusive se algum arquivo do meio do lote falhar. Coberto por novo teste em `tests/test_app_tif.py`.
- **Quantidade de métricas explícita na interface (2026-07-07)**: antes as mensagens de progresso
  diziam só "calculando métricas...", sem indicar quantas. Agora aparecem contagens explícitas em
  todo o fluxo — ex.: "Calculando 20 métricas por classe + 10 métricas de nível de paisagem (30 no
  total)...", "Calculando (3/20): ...", cabeçalho "🌎 Métricas da paisagem (nível global) — 10/10:".
- **Área de interesse por limite municipal via IBGE (2026-07-09)**: a Seção 1 do fluxo ("Área de
  interesse") ganhou uma segunda opção além de ponto+buffer: "🏘️ Limite municipal (IBGE)" — dois
  seletores (UF → município, via API de localidades do IBGE) buscam o polígono oficial do
  município na API de malhas territoriais do IBGE (`_ibge_get_ufs`/`_ibge_get_municipios`/
  `_ibge_get_municipio_geojson` em [app.py](app.py), todas com `st.cache_data` de 24h) e mostram um
  preview do limite num mapa folium antes do cálculo. Sem slider de buffer nesse modo — a área é o
  limite municipal inteiro. Funciona com as duas fontes de dados: no MapBiomas/Earth Engine, o
  polígono vira a `ee.Geometry` da região (no lugar do buffer circular); no GeoTIFF próprio,
  `extract_landscape_from_tif` ganhou o parâmetro `region_geojson` — generaliza o recorte (antes só
  um buffer circular ao redor de um ponto) para aceitar qualquer polígono, incluindo a lógica de
  reprojeção automática para CRS geográfico (a janela de recorte pré-reprojeção agora usa o
  bounding box do município em vez de `lon/lat ± margem`). Segue a mesma regra de "nunca fabricar
  dado" do resto do app: se a API do IBGE falhar, o fluxo pára com uma mensagem explicando a causa
  em vez de inventar um limite. `db.metric_results` ganhou colunas `municipio_codigo`/
  `municipio_nome`/`municipio_uf`/`ano` (migração via `ALTER TABLE` defensivo em `init_db`) para
  identificar essas análises no histórico e na matriz socioecológica (abaixo). Coberto por
  `tests/test_app_ibge.py`.
- **Predição de anos futuros via cadeia de Markov (2026-07-09)**: nova subseção "🔮 Predição para
  anos futuros" dentro da comparação entre múltiplos GeoTIFFs (2+ anos identificados pelo nome do
  arquivo, calculados na mesma sessão — não a partir do cache, que só guarda os valores das
  métricas, não os pixels). `_build_transition_matrix` (app.py) monta a matriz de transição
  classe-a-classe somando as transições pixel-a-pixel de todos os pares de anos consecutivos
  disponíveis (reamostra por nearest-neighbor via `scipy.ndimage.zoom` quando dois arquivos têm
  shapes diferentes); `_project_future_landcover` projeta a proporção de cada classe para os anos
  informados pelo usuário via potência fracionária da matriz (`scipy.linalg.fractional_matrix_power`
  — o "passo" é o intervalo médio entre os anos históricos disponíveis). Resultado: tabela +
  gráfico Altair (linha sólida para o histórico observado, tracejada para a projeção, ancorada no
  último ano observado para não deixar um salto visual) + CSV para download. Método explicitamente
  não-espacial (só projeta proporções agregadas, não um mapa futuro) e assume estacionariedade das
  probabilidades de transição — avisos claros na própria UI. Escopo desta primeira versão:
  multi-arquivo GeoTIFF apenas (não uma extração multi-ano automática via MapBiomas/Earth Engine,
  que exigiria N chamadas adicionais ao GEE por análise — possível melhoria futura). Coberto por
  `tests/test_app_markov.py`.
- **Matriz socioecológica — SSE (2026-07-09)**: nova seção "🧬 Matriz socioecológica (SSE)",
  visível assim que o usuário tem pelo menos uma análise salva. `_build_sse_matrix` (app.py) agrega
  TODO o histórico já persistido em `db.metric_results` (não só a análise atual) numa única matriz
  multivariada — uma linha por análise salva, colunas = proporção de área por classe (wide) +
  métricas de nível de paisagem (SHDI, CONTAG etc.) + identificação (label, fonte, município/UF/ano,
  data). O usuário pode anexar um CSV próprio com variáveis socioeconômicas/hidroclimáticas
  (`municipio_codigo` ou `municipio_nome` + opcionalmente `ano` como chave de junção — qualquer
  outra coluna é livre), casado via `pd.merge(how="left")`; linhas sem correspondência ficam com as
  colunas externas vazias (nunca um valor inventado) e a UI reporta quantas linhas casaram. Quando
  há município identificado, a matriz é enriquecida automaticamente com população estimada do IBGE
  (`_ibge_get_populacao_estimada`, agregado SIDRA 6579 — melhor esforço, `None` silencioso se a
  busca falhar). Inclui um heatmap de correlação (Altair, par diverging vermelho↔azul com meio-tom
  cinza, validado pela skill de dataviz do projeto) entre as colunas numéricas, e download em CSV.
  Coberto por `tests/test_app_sse.py`.
- **Correções de UX/UI (2026-07-09)**: revisão do app inteiro identificou dois problemas
  recorrentes, corrigidos nesta sessão — (1) vários cabeçalhos usavam
  `color:black; background-color:yellow/lightgreen` **hardcoded** (`_render_landscape_metrics` e
  várias seções de `main()`), o que ficava ilegível/destoante no tema escuro do Streamlit (o bloco
  continuava claro mesmo com o resto da UI escura); substituídos por um helper único
  `_section_header` (borda colorida à esquerda, sem cor de texto/fundo fixa — herda o tema ativo do
  usuário), e os títulos principais (`main()`/`auth.render_landing_page`) passaram a usar
  `st.title`/`st.info` nativos no lugar de HTML com `color:Blue`/caixa verde fixa. (2)
  `_render_metric_chart` tinha dois parágrafos longos ("Análise Detalhada"/"Considerações Finais")
  praticamente idênticos repetidos a cada uma das 12 métricas reveladas progressivamente — texto
  genérico que não mudava com os dados, só ruído/scroll sem informação nova; substituído por uma
  linha curta e factual (classe com maior/menor valor da métrica). A numeração das seções do fluxo
  principal foi ajustada para acomodar a nova Seção 1 (ponto vs. município): 1) Área de interesse →
  2) Fonte dos dados → 3) Buffer (só modo ponto) → 4) Calcular métricas.
- **Métricas por município em lote via shapefile (2026-07-17)**: nova seção independente "📦
  Métricas por município (lote via shapefile)" (`_render_municipio_batch_section`, entre a Matriz
  SSE e a Seção 1 do fluxo de análise única) — cobre o caso de uso de ter o shapefile de municípios
  do IBGE (ex.: todos os municípios de uma UF) e um GeoTIFF próprio, e querer as métricas de
  fragmentação de TODOS os municípios de uma vez, em vez de rodar a análise de município único
  (Fase 6, item acima) manualmente para cada um. Escopo desta primeira versão: só GeoTIFF próprio
  (não MapBiomas/GEE — exigiria 1 chamada ao Earth Engine por município, potencialmente centenas
  por lote). Detalhes:
  - **Autodetecção de colunas**: shapefiles de municípios variam o nome das colunas de
    identificação entre fontes/anos; `_detect_municipio_columns` casa (case-insensitive) contra
    nomes comuns da malha do IBGE (`CD_MUN`/`NM_MUN`/`SIGLA_UF` e variantes) e pré-seleciona os
    `st.selectbox` de código/nome (obrigatórios) e UF (opcional) — sempre editáveis na UI caso a
    detecção erre.
  - **Reuso do pipeline de GeoTIFF sem reescrever o arquivo por município**:
    `extract_landscape_from_tif` foi dividida em `_save_uploaded_tif_to_temp` (salva o arquivo uma
    vez) e `_clip_raster_at_path` (recorta/reprojeta a partir de um caminho já salvo em disco) —
    refactor que preserva o comportamento e a assinatura públicos (confirmado pelos testes
    existentes de `test_app_tif.py`/`test_app_ibge.py`, sem alteração). `_run_municipio_batch`
    chama `_save_uploaded_tif_to_temp` uma única vez e `_clip_raster_at_path` uma vez por
    município, em vez de reabrir/reescrever o mesmo GeoTIFF centenas de vezes.
  - **Isolamento de erro por município**: diferente da regra "nunca fabricar dado" do resto do app
    (que interrompe todo o processamento se a extração falhar), aqui uma falha num único município
    (ex.: polígono fora da extensão do raster) não derruba o lote inteiro — vira uma linha na lista
    de erros exibida na UI, e o lote segue para o próximo município. Nenhuma métrica é inventada;
    municípios com erro simplesmente não geram linha na planilha de saída.
  - **Cache reaproveitado**: cada município processado é salvo via `db.save_metric_result` (mesma
    fingerprint de `_compute_fingerprint`, variando `municipio_codigo`), então uma nova execução do
    mesmo lote (ex.: após uma interrupção no meio de centenas de municípios) pula os municípios já
    calculados — e os resultados também passam a aparecer na Matriz SSE automaticamente, por já
    usarem o mesmo `municipio_codigo`/`municipio_nome`/`municipio_uf` daquela tabela.
  - **Saída**: planilha `.xlsx` com 2 abas (`_build_municipio_batch_workbook`) — "paisagem" (1
    linha por município, métricas de nível de paisagem) e "classe" (formato longo, 1 linha por
    combinação município+classe) — formato escolhido para não explodir em centenas de colunas
    (uma aba "larga" por classe×métrica). CSVs de cada aba também disponíveis como alternativa.
    Nova dependência: `openpyxl` (`requirements.txt`).
  - Coberto por `tests/test_app_municipio_batch.py` (detecção de colunas, processamento em lote com
    isolamento de erro, reuso de cache, montagem da planilha).
- **Fase 10 — Dados de referência nacionais pré-carregados no banco (2026-07-26)**: quatro tabelas
  novas em `backend/app/db/` (`municipios.py`, `mapbiomas_stats.py`, `prodes.py`,
  `ana_hidroclimatica.py`), mesmo idioma de `schema.py` (sem ORM/migration, `CREATE TABLE IF NOT
  EXISTS` + `ALTER TABLE` defensivo), populadas por scripts em `scripts/seed_*.py`:
  - **`municipios_malha`**: malha municipal do Brasil inteiro (~5.570 municípios), cacheada uma vez
    via `scripts/seed_municipios_malha.py` — elimina a dependência de chamada em tempo real à API
    do IBGE por município. Confirmado ao vivo que `GET /malhas/estados/{uf}?intrarregiao=municipio`
    já retorna a malha da UF segmentada por município (uma feature por `codarea`), então o script
    itera as 27 UFs em vez de ~5.570 chamadas individuais. `services/landscape.py::
    _get_municipio_geojson_cached` checa esse cache antes de cair no caminho antigo (chamada ao
    vivo ao IBGE) — nunca deixa de resolver um município só porque o cache ainda não cobriu aquela
    área. Nova rota `GET /api/ibge/municipios/{codigo}/malha` com o mesmo fallback.
  - **`prodes_desmatamento`**: registros de desmatamento do PRODES/INPE via WFS do GeoServer do
    TerraBrasilis (`scripts/seed_prodes.py`), para os 6 biomas monitorados (Amazônia, Cerrado,
    Caatinga, Mata Atlântica, Pampa, Pantanal — layers confirmadas ao vivo via `GetCapabilities`).
    Volume real descoberto em produção: só a camada da Amazônia tem ~835 mil features
    (`totalFeatures`) — a ingestão completa passa de 1-2 milhões de registros e leva horas; o
    script pagina via `startIndex`/`count`, mantém um checkpoint em disco
    (`scripts/.checkpoints/prodes.json`) para retomar sem re-baixar páginas já processadas, e isola
    erro por feature (loga e segue). O município é resolvido por junção espacial (centroide da
    feature dentro do polígono do município, via `shapely.strtree.STRtree` — muito mais rápido que
    varredura linear contra os ~5.570 municípios); fica `NULL` se a malha daquele município ainda
    não estiver cacheada, nunca um palpite. Área (`area_km`) e ano (`year`) vêm prontos do próprio
    INPE, confirmados via amostra ao vivo — não recalculados. Nova rota
    `GET /api/prodes/municipio/{codigo}`.
  - **`mapbiomas_municipio_stats`**: área (hectares) por classe/ano/município — decisão de projeto
    (confirmada com o usuário): agregado, não pixel raster (guardar o raster nacional de 20 anos
    seria da ordem de dezenas de TB). MapBiomas não tem API pública para isso (só Excel de download
    manual em brasil.mapbiomas.org/estatisticas/, confirmado via pesquisa); `scripts/
    seed_mapbiomas_stats.py` calcula via Earth Engine (`reduceRegions` + `frequencyHistogram` contra
    `municipios_malha`, reaproveitando a mesma lista de assets com fallback de
    `_extract_mapbiomas_pixels`, em lotes por UF) como caminho principal, com `--from-excel` como
    alternativa caso prefira importar o arquivo oficial manualmente. **Não validado ao vivo nesta
    sessão** — sem credencial de conta de serviço do Earth Engine disponível para testar; a lógica
    de agregação (histograma de pixels → hectares) e o parsing do Excel foram implementados mas
    ainda não rodaram contra dado real. Nova rota `GET /api/mapbiomas/serie/{municipio_codigo}` —
    melhora a predição de Markov já existente (hoje limitada a upload manual de GeoTIFFs) ao
    oferecer histórico real de qualquer município já ingerido, sem exigir upload.
  - **`ana_estacoes`/`ana_serie_historica`**: schema pronto, mas ingestão real bloqueada — a API
    HidroWebService da ANA exige credencial pedida manualmente por e-mail a `hidro@ana.gov.br`
    (assunto "Solicitação de acesso à API", confirmado no manual oficial), não é algo resolvido por
    código. `scripts/seed_ana_hidroclimatica.py` já verifica a credencial e para com uma mensagem
    explicando o bloqueio em vez de fabricar dado. Rotas `GET /api/ana/estacoes` e
    `GET /api/ana/serie/{codigo}` já existem, retornam lista vazia até a ingestão real rodar.
  - Explicitamente fora desta fase (decisão registrada com o usuário): verificação/diff automático
    de "o que mudou na fonte" desde a última ingestão, e integração automática desses dados na
    Matriz SSE/clustering — ambos ficam para uma fase futura.
  - Coberto por `tests/test_backend_db_national.py` (16 testes, CRUD/upsert dos 4 módulos novos).
    De brinde, corrigido um bug de colisão de nomes pré-existente entre o módulo `app` (Streamlit,
    raiz) e o pacote `app` do backend quando a suíte inteira roda numa única sessão pytest — os
    dois arquivos de teste que importam o pacote `app` do backend agora descartam qualquer
    `sys.modules["app"]` stale antes de importar (`tests/test_backend_app.py` e
    `tests/test_backend_db_national.py`); suíte completa: 138 testes passando (era 121 + esse bug
    de colisão intermitente).
- **Remoção completa do Streamlit + padronização em Python (backend) / TypeScript (frontend)
  (2026-07-27)**: `app.py` (2886 linhas), `auth.py`, `.streamlit/` e as dependências
  `streamlit`/`altair`/`streamlit-folium`/`folium` (raiz `requirements.txt`) foram apagados — o
  backend FastAPI + frontend `static/` já eram o caminho real desde a migração anterior, essa
  fase só termina de desligar o que ainda coexistia. Detalhes:
  - **`landscape_core.py`/`clustering.py`/`supervised_models.py`** (lógica pura, sem Streamlit)
    movidos de vez para `backend/app/services/` — os 3 consumidores (`services/landscape.py`,
    `api/routes/sse.py`/`supervised.py`) trocaram o padrão frágil `_load_legacy_module`
    (`sys.path.insert` + `importlib.import_module`) por import de pacote normal. De brinde: `sse.py`
    e `supervised.py` tinham o mesmo `parents[N]` errado (uma camada rasa demais) que só não
    quebrava por acidente — `metrics.py` importa primeiro em `main.py` e deixa o `sys.path` correto
    como efeito colateral antes deles rodarem. Corrigido para `parents[4]`, correto por conta
    própria agora.
  - **`db.py` (raiz) apagado por completo** — só tinha 3 funções ainda vivas
    (`get_user_settings`/`save_user_settings`/`delete_user_settings`, usadas por
    `api/routes/user.py`/`lgpd.py` via `import db`), migradas para um módulo próprio
    `backend/app/db/user_settings.py` (mesmo padrão de `credentials.py`/`users.py`, sem truque de
    `sys.path`). O resto (`get_credentials`/`save_credentials`/`create_user`/`verify_user`/
    `*_metric_result*`) já era código morto — o backend tem equivalentes próprios há tempo.
    `backend/app/db/schema.py::init_db()` nunca criava a tabela `user_settings` (só o `db.py`
    antigo criava) — um deploy do zero só com o backend ficaria sem essa tabela; corrigido.
  - **Suíte de testes**: `tests/conftest.py` parou de importar `streamlit`/expor `fake_secrets`/
    `temp_db` (o `db.py` que sumiu). Os ~9 arquivos `test_app_*.py`/`test_auth.py`/`test_db*.py`
    (cobriam `landscape_core.py` só indiretamente, via `import app` + `.__wrapped__` para
    contornar o `@st.cache_data`) foram portados para importar `landscape_core`/`sse`/`clustering`/
    `supervised_models` diretamente do backend, com nomes novos (`test_landscape_core_*.py`,
    `test_backend_sse.py`) — corpos de teste preservados, só o alvo do import mudou. `test_db.py`/
    `test_db_metrics.py`/`test_auth.py`/`test_app_structure.py` foram descartados (testavam código
    morto ou um bug estrutural que só existia no `app.py`), sem perda de cobertura real —
    equivalente já existe em `tests/test_backend_db_auth.py`/`test_backend_api_routes.py`. Suíte
    completa: mesma contagem efetiva de antes, zero `import streamlit`/`app`/`auth`/`db` restante.
  - **3 features "concluídas" no histórico só existiam em `app.py`, sem rota de API nem UI no
    frontend novo** (descoberto ao portar os testes, não durante o resto da migração):
    - **Predição de anos futuros (Markov)**: pequena e autocontida (2 funções puras, sem
      dependência de outra coisa) — movida para `landscape_core.py` com seus testes. Ainda sem
      endpoint/UI própria.
    - **Relatório HTML multi-arquivo + gráfico de comparação (matplotlib)**: descartada — o
      frontend novo renderiza gráficos no cliente (Chart.js), sem necessidade clara de um
      equivalente server-side.
    - **Métricas por município em lote via shapefile**: só a parte pura
      (`_detect_municipio_columns`) foi portada — o resto depende de `uploaded_file_to_gdf`
      (também nunca portada, sem uso em lugar nenhum do backend hoje) e de persistência
      (`db.get_metric_result`/`save_metric_result`, o `db.py` que saiu) — esforço de port maior,
      separado, não feito aqui.
  - **Bug real encontrado e corrigido ao escrever o teste da Matriz SSE**: `backend/app/api/routes/
    sse.py::_build_sse_matrix` iterava nomes de MÉTRICA (`class_metrics.columns`) e pegava só
    `.iloc[0]` (a primeira linha) — para qualquer análise com mais de uma classe presente (o caso
    normal), isso descartava todas as classes menos a primeira, sem gerar coluna `pct_*` nenhuma.
    `/api/sse/matrix` estava retornando dado incompleto/errado em produção desde que essa rota foi
    escrita. Corrigido para pivotar `proportion_of_landscape` por classe (mesma lógica do `app.py`
    antigo). Coberto por `tests/test_backend_sse.py` (4 testes).
  - **Frontend migrado para TypeScript**: `frontend-src/app.ts` (porte 1:1 de `static/app.js`, 798
    linhas — mesmo comportamento, só tipado, sem redesenhar UI) compila via `tsc` (`module: "none"`,
    sem bundler/dev-server — decisão consciente: o app é multi-página com handlers inline
    `onclick=`/`onchange=`/`onsubmit=`, um bundler/SPA-router não traria benefício aqui) para
    `static/app.js` (`tsconfig.json`, `outFile`). `static/app.js` virou artefato gerado
    (`.gitignore`), nunca mais editado à mão. `Dockerfile` ganhou um estágio Node isolado
    (`frontend-build`) que compila e copia só o `app.js` final para a imagem Python — Node nunca
    entra na imagem de produção. Diff do compilado contra o `app.js` anterior confirmado
    linha-a-linha equivalente (só formatação/`"use strict"` — nenhuma mudança de comportamento).
  - **Achado à parte, fora do escopo desta migração**: a Fase 8 (abaixo) descreve "Suporte a Banco
    de Dados PostgreSQL" como concluído, mas `backend/app/db/*` usa só `sqlite3` puro — esse
    suporte só existia em `db.py::_get_db_url()` (Streamlit-era), que esta migração apagou. Ou
    seja, o backend nunca teve de fato suporte a Postgres — só fica registrado aqui, não é escopo
    resolver.

### 🔄 Mudança de arquitetura (2026-07-04): login por e-mail/senha + JWT, com Google OAuth opcional

A Fase 2 originalmente usava só `st.login("google")` (OAuth nativo do Streamlit). O app estava
configurado com valores fictícios (`fake-client-id`) e retornava `Erro 401: cliente inválido` do
Google. Em vez de depender só da credencial OAuth, foi adicionado um sistema de contas próprio
(e-mail/senha) como modo sempre disponível, e o Google OAuth virou um modo adicional opcional:

- Cadastro aberto por e-mail/senha (sem confirmação de e-mail), com hash bcrypt em `data/app.db`
  (tabela `users`), nunca em texto puro.
- Sessão via JWT assinado (`jwt_secret_key`) guardado em `st.session_state` — trade-off aceito:
  simples de implementar, mas a sessão não sobrevive a um refresh da página (sem cookie).
- Login com Google continua disponível (`st.login()`, sem argumento de provedor — `secrets.toml`
  usa a seção `[auth]` de provedor único, não `[auth.google]`) quando configurado com credencial
  OAuth real; convive com o modo e-mail/senha, cada um cuidando da própria sessão.
- Depende de `PyJWT` e `bcrypt` (novo) além de `Authlib`/`httpx` (mantidos para o modo Google).

### ⚠️ Bloqueio conhecido

- Sem as credenciais do Earth Engine cadastradas pelo próprio usuário (fluxo da Fase 3), a
  aplicação sobe normalmente mas para na etapa de inicialização do Earth Engine — comportamento
  esperado, não um bug.
- O e-mail de cadastro não é verificado (sem confirmação por e-mail) — é só uma chave de conta
  local, não uma prova de propriedade do endereço.
- Sessão de login não sobrevive a um refresh (F5) da página, por guardar o JWT em
  `st.session_state` em vez de cookie.

---

## Próxima fase

## Atividades pendentes (snapshot 2026-07-27, atualizado ~14:06)

Resumo das tarefas abertas e do estado atual dos jobs de ingestão em segundo plano. Esta seção
é pensada como ponto de retomada caso seja necessário continuar o trabalho depois.

- **Criar schema (4 tabelas) + scripts de seed + rotas** — concluído
- **Ligar routers/tabelas novas e validar boot limpo do backend** — concluído (backend sobe limpo,
  `/health` e `/` respondem 200)
- **Escrever e rodar testes unitários (16 novos) + corrigir bug de colisão app/app** — concluído.
  `tests/test_backend_api_routes.py` tinha 2 bugs reais que impediam até a coleta dos testes: (1)
  todas as funções `def test_*` usavam `await` sem serem `async def`; (2) a fixture criava
  `httpx.AsyncClient(app=app, ...)`, parâmetro removido no httpx 0.28 (precisa de
  `transport=httpx.ASGITransport(app=app)`). Corrigido; suíte completa agora: **147/147 passando**
  (era 138 antes desta correção).
- **Criar utilitário de reconserto de município NULL no PRODES** — concluído
  (`scripts/reresolve_prodes_municipios.py`, já existia pronto).
- **Malha municipal (IBGE)** — **concluída**: 5.570 municípios, 27/27 UFs, 0 erros
  (`seed_municipios.log`, 2026-07-26 10:40).
- **Rodar `reresolve_prodes_municipios.py`** — concluído nesta sessão: 768.596 de 768.829 registros
  pendentes ganharam município (768.596/768.829 ≈ 99,97%). Os ~233 restantes provavelmente têm
  centroide fora de qualquer polígono da malha (litoral/fronteira) — não é um bug, é o
  comportamento esperado de "nunca fabricar dado". **Atenção**: rodar esse script enquanto
  `seed_prodes.py` está inserindo ativamente causou 12 erros transitórios de "database is locked"
  (perda de 12 features de ~1,86M linhas, negligenciável) — evitar rodar os dois ao mesmo tempo em
  execuções futuras, ou aceitar essa perda mínima.
- **PRODES** — **concluído (2026-07-27)**: todos os 6 biomas monitorados no banco — Amazônia
  (802.282), Cerrado (2.335.909), Caatinga (556.926), Pampa (205.339), Pantanal (37.155) — total
  **3.937.611** registros. Terminou sozinho em segundo plano (log mostra o resumo final por bioma);
  bem maior do que a estimativa inicial de "~835k só a Amazônia" sugeria.
- **MapBiomas via Earth Engine** — **concluído (2026-07-27)**: 540/540 combinações UF×ano
  (27 UFs × 2004–2023) em `mapbiomas_municipio_stats`. A credencial de conta de serviço de
  `ederbtos@gmail.com` (`land-638@land-501423.iam.gserviceaccount.com`, projeto `land-501423`) já
  estava salva (criptografada) em `user_credentials` desde 2026-07-05 — decifrada de novo nesta
  sessão para retomar o job depois que ele parou silenciosamente em SP→SE (sem traceback, mesmo
  padrão de "processo encerrado externamente" já visto no PRODES). Achado ao investigar: o
  fallback de asset em `pick_asset_for_band`/`_extract_mapbiomas_pixels` (`except Exception:
  continue`) mascara qualquer erro real (nesse caso, `SSLError`/`SSLEOFError` batendo em
  `oauth2.googleapis.com`/`earthengine-highvolume.googleapis.com`) como se fosse simplesmente "esse
  asset não tem essa banda" — por isso o log mostrava dezenas de "Nenhum asset MapBiomas..." em
  menos de 1 segundo (rápido demais para chamadas de rede reais), quando na verdade era a sessão do
  Earth Engine caindo. Retomado com sucesso após reautenticar; **ano 2024 confirmado indisponível
  em todas as UFs testadas** (mesmo padrão já visto em SC) — não é um bug, a coleção do MapBiomas
  ainda não publicou `classification_2024`. Possível melhoria futura (fora do escopo agora): não
  mascarar erros de rede/autenticação como "asset ausente" nesse fallback.
- **ANA hidroclimática** — bloqueado (aguardando credencial pedida por e-mail a
  `hidro@ana.gov.br`) — ação do operador, não de código. Único item de dados ainda pendente na
  Fase 10.
- **Validar PRODES e IBGE ao vivo (pilotos reais)** — parcialmente feito (dados reais completos no
  banco agora); falta uma validação funcional das rotas `/api/prodes/municipio/{codigo}` e
  `/api/ibge/municipios/{codigo}/malha` contra o app rodando de ponta a ponta.
- **Agendar/verificar health-check periódico para os jobs long-running** — não se aplica mais:
  PRODES e MapBiomas terminaram (ver acima); só resta ANA, que nem chegou a rodar (bloqueada por
  credencial).

### Próximos passos sugeridos

- Rodar `scripts/reresolve_prodes_municipios.py` de novo agora que o PRODES terminou totalmente —
  **feito (2026-07-27 14:08)**: 622 registros sem município (mais do que os ~233 anteriores, porque
  Cerrado/Caatinga/Pampa/Pantanal terminaram de ingerir depois da última passada), **0 resolvidos
  nesta rodada** — todos os 622 têm centroide fora de qualquer polígono da malha (provavelmente
  litoral/fronteira), comportamento esperado de "nunca fabricar dado", não um bug.
- Validar manualmente as rotas novas (`/api/prodes/...`, `/api/ibge/...`, `/api/mapbiomas/...`,
  `/api/ana/...`) contra o backend rodando, com um token real.
- Fase 4 (deploy) segue pendente de decisão de infraestrutura do usuário — ver seção abaixo.

### Fase 4 — Deploy

**Regressão corrigida (2026-07-27)**: a migração de Streamlit para backend FastAPI + frontend
estático (commit `af4a62f`, 2026-07-25) reescreveu `Dockerfile`/`docker-compose.prod.yml` para a
nova arquitetura (porta 8000, variáveis de ambiente em vez de `secrets.toml`), mas nesse processo
o serviço `caddy` foi removido inteiramente de `docker-compose.prod.yml` — a stack de produção
ficou publicando a porta 8000 direto no host, **sem HTTPS**, e `Caddyfile.example` continuava
apontando para a porta antiga (8501). Corrigido nesta sessão:

- `docker-compose.prod.yml`: serviço `caddy` restaurado (portas 80/443, volumes de certificado),
  `app` volta a não publicar porta para o host (`expose: 8000`, só acessível via Caddy), segredos
  via `env_file: backend/.env` (em vez do volume de `secrets.toml` do modelo antigo).
- `Caddyfile.example`: `reverse_proxy app:8501` → `app:8000`.
- Novo `backend/.env.example` (não existia — equivalente ao antigo
  `.streamlit/secrets.toml.example`, com `jwt_secret_key`, `app_encryption_key`, `cors_origins`,
  `cookie_secure`, credenciais Google opcionais).
- `scripts/deploy.sh`: checagem de pré-requisito trocada de `.streamlit/secrets.toml` para
  `backend/.env`.
- README.md: seções de instalação/deploy e "Estrutura do Projeto" atualizadas para a arquitetura
  atual (`backend/` + `static/`, `app.py`/`auth.py`/`db.py` documentados como versão anterior
  substituída).

Toda a mecânica está automatizada de novo; o que falta é só a execução — decisão de infraestrutura
que cabe a quem for hospedar o app:

1. Escolher onde rodar (qualquer servidor com Docker: VPS próprio, ex. Hetzner/DigitalOcean/OVH,
   ou uma plataforma gerenciada como Railway/Render que já resolve HTTPS por você — nesse caso
   `docker-compose.prod.yml`/Caddy não são necessários).
2. Se for VPS com Docker: apontar um domínio (registro DNS tipo A) para o IP do servidor, liberar
   as portas 80/443 no firewall, preencher `backend/.env` (a partir do `backend/.env.example`, com
   `jwt_secret_key`, `app_encryption_key` e `cors_origins` reais) e rodar
   `./scripts/deploy.sh seu-dominio.com` — o script gera o `Caddyfile` e sobe a stack (app + Caddy).
3. Agendar `./scripts/backup-db.sh` via `cron` (opcionalmente com `BACKUP_REMOTE` apontando para
   fora do servidor) para que `data/app.db` sobreviva a rebuilds/migrações — a mecânica já existe,
   falta só decidir o destino externo do backup.

---

## Como rodar hoje

Detalhes completos (pré-requisitos, geração das chaves) em [README.md](README.md#-instalação). Resumo:

### Local (sem Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# edite backend/.env: jwt_secret_key, app_encryption_key e cors_origins

npm install
npm run build                   # compila frontend-src/ -> static/app.js

cd backend && uvicorn app.main:app --reload
```

### Docker

```bash
cp backend/.env.example backend/.env
# edite backend/.env: jwt_secret_key, app_encryption_key e cors_origins
docker compose up --build
```

Acesse `http://localhost:8000`. Crie uma conta (e-mail/senha) no botão "Entrar / Cadastrar" — ou,
se `google_client_id`/`google_client_secret`/`google_redirect_uri` estiverem configurados em
`backend/.env`, use o botão "Entrar com Google" — e, depois de logado, cole sua própria credencial
de conta de serviço do Earth Engine na interface (não vai em `backend/.env`).
