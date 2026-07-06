"""
Teste de regressão estrutural para um bug encontrado em 2026-07-05: o bloco de
cálculo do PyLandStats (instancia Landscape, computa métricas, seta
st.session_state["metrics_ready"] = True) estava aninhado dentro do `else:`
do `if data_source == "MapBiomas (Google Earth Engine)": ... else:` — ou
seja, só rodava para a fonte "Meu raster (GeoTIFF)". Escolhendo MapBiomas e
clicando em "Calcular métricas", a extração de pixels rodava normalmente mas
o pipeline nunca chegava a calcular as métricas nem a marcar
metrics_ready=True: nenhum resultado aparecia, sem nenhum erro visível.

Esse bug já existia antes de qualquer mudança feita nesta sessão (confirmado
via `git show 0331287:app.py`, commit anterior ao início deste trabalho) —
não foi introduzido por um refactor específico, mas testar contra o retorno
dele é barato e vale a pena, já que é o tipo de erro de indentação fácil de
reintroduzir sem um teste de UI completo (que exigiria uma credencial real
do Earth Engine, fora do escopo de CI — ver documentation/13_testing.md).
"""
import inspect

import app


def test_metrics_ready_assignment_is_not_nested_inside_geotiff_only_branch():
    source = inspect.getsource(app.main)
    lines = source.splitlines()

    if_idx = next(
        i for i, line in enumerate(lines) if 'if data_source == "MapBiomas' in line
    )
    if_indent = len(lines[if_idx]) - len(lines[if_idx].lstrip(" "))

    ready_idx = next(
        i for i, line in enumerate(lines) if 'session_state["metrics_ready"] = True' in line
    )
    ready_indent = len(lines[ready_idx]) - len(lines[ready_idx].lstrip(" "))

    assert ready_idx > if_idx, "session_state['metrics_ready'] deveria vir depois do if/else de data_source"
    assert ready_indent <= if_indent, (
        "session_state['metrics_ready'] = True parece aninhado dentro do if/else de "
        "data_source — isso reproduz o bug em que escolher MapBiomas nunca chega a "
        "calcular/exibir as métricas (só funcionava para o GeoTIFF próprio)."
    )
