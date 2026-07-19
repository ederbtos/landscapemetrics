# Roadmap — Landscape Metrics Extractor

## Progresso geral: 96%

| Fase | Descrição | Status | % |
| --- | --- | --- | --- |
| 1 | Landing page | ✅ Concluída | 100% |
| 2 | Login (e-mail/senha + JWT, com Google OAuth opcional) | ✅ Concluída | 100% |
| 3 | Credenciais por usuário | ✅ Concluída | 100% |
| 4 | Deploy (HTTPS) | 🔧 Automatizada (1 comando), falta decisão de infra + execução | 75% |
| 5 | Motor de métricas de paisagem | ✅ Concluída | 100% |
| 6 | Área municipal (IBGE), matriz socioecológica (SSE), predição de anos futuros (Markov) e lote por município via shapefile | ✅ Concluída | 100% |

> O percentual mede fases do roadmap entregues. A Fase 4 tem toda a mecânica pronta e
> automatizada em um único comando ([scripts/deploy.sh](scripts/deploy.sh), usando
> [docker-compose.prod.yml](docker-compose.prod.yml) e [Caddyfile.example](Caddyfile.example)),
> mas os 100% só são atingidos com uma publicação real, o que depende de uma decisão que só quem
> hospeda o app pode tomar: qual servidor/domínio usar. Ver "Fase 4 — Deploy" abaixo. A Fase 5
> (adicionada em 2026-07-07) cobre o motor de cálculo em si — fonte de dados (MapBiomas/GeoTIFF
> próprio, um ou vários arquivos), reprojeção automática, e a cobertura de métricas do FRAGSTATS
> (classe + paisagem). A Fase 6 (adicionada em 2026-07-09) cobre área de interesse por limite
> municipal (IBGE), a matriz socioecológica (SSE) e a predição de anos futuros via cadeia de
> Markov — ver "Status atual" abaixo para o detalhamento item a item.

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

### Fase 4 — Deploy

Toda a mecânica está automatizada; o que falta é só a execução — decisão de infraestrutura que
cabe a quem for hospedar o app:

1. Escolher onde rodar (qualquer servidor com Docker: VPS próprio, ex. Hetzner/DigitalOcean/OVH,
   ou uma plataforma gerenciada como Railway/Render que já resolve HTTPS por você — nesse caso
   `docker-compose.prod.yml`/Caddy não são necessários).
2. Se for VPS com Docker: apontar um domínio (registro DNS tipo A) para o IP do servidor, liberar
   as portas 80/443 no firewall, preencher `.streamlit/secrets.toml` (a partir do
   `.streamlit/secrets.toml.example`, com `jwt_secret_key` e `app_encryption_key` reais) e rodar
   `./scripts/deploy.sh seu-dominio.com` — o script gera o `Caddyfile` e sobe a stack.
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
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml: jwt_secret_key e app_encryption_key
streamlit run app.py
```

### Docker

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite .streamlit/secrets.toml: jwt_secret_key e app_encryption_key
docker compose up --build
```

Acesse `http://localhost:8501`. Crie uma conta (e-mail/senha) na aba "Criar conta" — ou, se a
seção `[auth]` do Google estiver configurada em `secrets.toml`, use o botão "Entrar com Google" —
e, depois de logado, cole sua própria credencial de conta de serviço do Earth Engine na interface
(não vai em `secrets.toml`).
