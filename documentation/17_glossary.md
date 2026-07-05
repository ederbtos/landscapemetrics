# 17 — Glossário

## Termos de negócio / domínio

| Termo | Significado |
| --- | --- |
| **Métrica de paisagem** | Medida quantitativa da composição (quanto de cada classe existe) ou configuração (como as manchas de cada classe estão distribuídas espacialmente) de uma paisagem |
| **Mancha (patch)** | Área contígua de uma mesma classe de cobertura do solo |
| **Buffer** | Área circular definida por um raio (em metros) ao redor do ponto de interesse selecionado |
| **Ponto de interesse (ROI)** | Localização (latitude/longitude) escolhida pelo usuário como centro da análise |
| **Classe de cobertura do solo** | Categoria de uso/cobertura da terra (ex.: Floresta, Pastagem, Água) segundo a legenda do MapBiomas |
| **Proporção da paisagem** | Percentual da área do buffer ocupado por uma classe específica |
| **Índice de forma da paisagem (LSI)** | Medida de quão irregular é o formato das manchas em relação a um círculo/quadrado perfeito |
| **Dimensão fractal** | Medida da complexidade geométrica do contorno das manchas |

## Termos técnicos

| Termo | Significado |
| --- | --- |
| **MapBiomas** | Iniciativa multi-institucional que produz mapas anuais de uso e cobertura da terra do Brasil, publicados como assets públicos no Google Earth Engine |
| **Google Earth Engine (GEE)** | Plataforma de processamento geoespacial em nuvem usada para acessar e processar os rasters do MapBiomas |
| **Collection (MapBiomas)** | Versão/geração dos mapas do MapBiomas (ex.: Collection 9, 8, 7, 6) — cada uma pode ter esquema de classes e anos disponíveis diferentes |
| **Conta de serviço (service account)** | Credencial não-humana do Google Cloud usada para autenticar programaticamente contra o Earth Engine |
| **PyLandStats** | Biblioteca Python usada para calcular as métricas de paisagem a partir do array de classes |
| **GeoDataFrame (gdf)** | Estrutura de dados do `geopandas` que combina uma tabela com geometrias espaciais |
| **CRS (Coordinate Reference System)** | Sistema de referência de coordenadas de um dado espacial; pode ser geográfico (graus, ex. EPSG:4326) ou projetado/métrico (ex. UTM) |
| **GeoTIFF** | Formato de arquivo raster que embute georreferenciamento (CRS, resolução, extensão espacial) |
| **GeoJSON** | Formato de arquivo de texto (JSON) para representar geometrias geoespaciais (pontos, linhas, polígonos) |
| **Fernet** | Esquema de criptografia simétrica autenticada (biblioteca `cryptography`) usado para cifrar as credenciais do Earth Engine em repouso |
| **JWT (JSON Web Token)** | Token assinado usado para representar a sessão de login por e-mail/senha |
| **bcrypt** | Algoritmo de hash de senha com salt automático, usado para nunca guardar senhas em texto puro |
| **Rerun (Streamlit)** | Modelo de execução do Streamlit: o script inteiro é reexecutado do topo a cada interação do usuário com um widget |
| **`st.session_state`** | Dicionário persistente do Streamlit usado para guardar estado entre reruns |
| **Caddy** | Servidor web usado como proxy reverso em produção, com emissão/renovação automática de certificado HTTPS via Let's Encrypt |
| **Upsert** | Operação de banco que insere um registro novo ou atualiza o existente, caso já haja um com a mesma chave (`INSERT ... ON CONFLICT DO UPDATE`) |
