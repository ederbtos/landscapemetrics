# 16 — Solução de Problemas

## "Falha na inicialização do Earth Engine"

**Sintoma**: mensagem de erro logo após cadastrar/atualizar a credencial, com um expander de
detalhes.

**Causas mais comuns** (na ordem sugerida pelo próprio app em `app.initialize_ee`):

1. JSON da conta de serviço incorreto ou incompleto.
2. Conta de serviço sem as permissões necessárias no GCP.
3. Earth Engine API não habilitada no projeto do GCP associado à conta de serviço.

**Como diagnosticar**: abra o expander "🔍 Detalhes do erro" na própria UI — a mensagem original
da exceção do SDK do Earth Engine aparece ali.

## "Você ainda não cadastrou suas credenciais" reaparece mesmo após cadastrar

**Causa provável**: `db.get_credentials` retorna `None` tanto para "nunca cadastrou" quanto para
"credencial corrompida ou `app_encryption_key` diferente da usada para cifrar" (ver
[04_database.md](04_database.md)). Se a credencial foi cadastrada anteriormente e o problema
começou após uma mudança de ambiente/segredo, suspeite de `app_encryption_key` diferente da
original.

**Como confirmar**: verifique se `.streamlit/secrets.toml` tem a mesma `app_encryption_key` usada
quando a credencial foi salva pela primeira vez. Não há como recuperar a credencial sem a chave
original — é necessário recadastrá-la.

## "Não foi possível extrair dados reais do MapBiomas para esta área"

**Causas possíveis** (listadas na própria mensagem de erro do app):

- Buffer muito pequeno para a área ter pixels válidos suficientes.
- Região sem cobertura no asset do MapBiomas.
- Instabilidade temporária do Earth Engine.

**Como resolver**: aumentar o raio do buffer, tentar novamente, ou selecionar outro ponto.

## "O GeoTIFF precisa estar em uma projeção métrica"

**Causa**: o raster enviado está em CRS geográfico (graus, ex.: EPSG:4326), mas o buffer é
definido em metros — reprojetar automaticamente o raster inteiro não é feito, pois seria custoso e
mudaria a resolução original. **Solução**: reprojetar o GeoTIFF para um CRS métrico (ex.: UTM da
zona correspondente) antes do upload.

## "A área do buffer não intersecta o raster enviado" / "Nenhum pixel válido dentro da área do buffer"

**Causa**: o ponto selecionado (ou o raio do buffer) cai fora da extensão espacial do GeoTIFF
enviado. **Solução**: confirmar que o raster realmente cobre a região do ponto escolhido, ou
reduzir/mover o buffer.

## "Você selecionou mais de um ponto" / "Nenhum ponto encontrado no arquivo"

**Causa**: o GeoJSON exportado do mapa contém mais de uma geometria, ou nenhuma geometria do tipo
ponto. **Solução**: no mapa, apague os desenhos extras antes de exportar, ou reexporte com apenas
um marcador.

## Sessão perdida ao atualizar a página (F5)

**Causa esperada, não um bug**: no modo de login por e-mail/senha, a sessão é um JWT guardado em
`st.session_state`, que é limpo a cada F5 (não há cookie). O login com Google, quando configurado,
não tem esse problema. Ver [11_security.md](11_security.md).

## Botão "Entrar com Google" não aparece

**Causa esperada**: a seção `[auth]` não está configurada (ou está incompleta) em
`.streamlit/secrets.toml` — o app opta por esconder o botão em vez de travar. **Solução**:
preencher `[auth]` conforme `.streamlit/secrets.toml.example`, ou seguir usando o login por
e-mail/senha (não é obrigatório configurar o Google).

## Erro ao subir com Docker: certificado HTTPS não é emitido

**Causas mais comuns**:

- DNS ainda não propagou (`dig +short seu-dominio.com` não retorna o IP do servidor).
- Portas 80/443 bloqueadas no firewall do servidor.

**Como diagnosticar**: `docker compose -f docker-compose.prod.yml logs -f caddy`.

## Erro de CRS envolvendo "DATABASE.LAYOUT.VERSION.MINOR" (Windows)

**Sintoma**: qualquer operação envolvendo CRS no GeoTIFF próprio (`extract_landscape_from_tif`)
falha com uma mensagem do PROJ mencionando `DATABASE.LAYOUT.VERSION.MINOR ... whereas a number >=
5 is expected` ou `The EPSG code is unknown`.

**Causa**: uma variável de ambiente `PROJ_LIB` (ou `PROJ_DATA`) definida globalmente no Windows —
comumente pelo instalador do PostgreSQL/PostGIS — aponta para um `proj.db` de uma versão do PROJ
incompatível com a que o `rasterio`/`pyproj` deste projeto esperam. Isso não é um bug do código:
é um conflito entre a instalação do PostGIS e a instalação Python usada pelo app, e afeta o app
de verdade (não só os testes) quando rodado **localmente sem Docker** nessa máquina — dentro do
container Docker não ocorre, pois a imagem não tem PostgreSQL instalado.

**Como resolver** (rodando localmente, fora do Docker): apontar `PROJ_LIB`/`PROJ_DATA`
explicitamente para o `proj_data` que vem dentro do próprio pacote `rasterio` instalado, antes de
rodar o app:

```powershell
$env:PROJ_LIB = (python -c "import rasterio, os; print(os.path.join(os.path.dirname(rasterio.__file__), 'proj_data'))")
$env:PROJ_DATA = $env:PROJ_LIB
streamlit run app.py
```

Os testes automatizados (`tests/conftest.py`) já aplicam essa mesma correção automaticamente, então
`pytest tests/` funciona independentemente dessa variável de ambiente da máquina.

## Upload de GeoTIFF grande falha ou trava

**Causa provável**: `server.maxUploadSize` (`.streamlit/config.toml`) e `MAX_TIF_SIZE`
(`app.py`) precisam bater — se um dos dois foi alterado sem o outro, uploads grandes podem ser
rejeitados de forma inconsistente entre o Streamlit e a validação da aplicação.
