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
    # Desde a introdução do modo multi-arquivo (2026-07-07), existe um segundo
    # ponto legítimo de `metrics_ready = True` (o loop de múltiplos GeoTIFFs,
    # que não passa pelo if/else de `data_source` — ele já sabe que a fonte é
    # "Meu raster"). Por isso, em vez de checar só a PRIMEIRA ocorrência,
    # verifica-se que PELO MENOS UMA ocorrência de `metrics_ready = True` vem
    # depois do if/else de `data_source` e não está aninhada dentro dele —
    # essa é a ocorrência alcançável pelo caminho de fonte única (MapBiomas ou
    # um só GeoTIFF), que é o que o bug original quebrava.
    source = inspect.getsource(app.main)
    lines = source.splitlines()

    if_idx = next(
        i for i, line in enumerate(lines) if 'if data_source == "MapBiomas' in line
    )
    if_indent = len(lines[if_idx]) - len(lines[if_idx].lstrip(" "))

    ready_indices = [
        i for i, line in enumerate(lines) if 'session_state["metrics_ready"] = True' in line
    ]
    assert ready_indices, "session_state['metrics_ready'] = True não encontrado em app.main"

    reachable_after_if_else = [
        i for i in ready_indices
        if i > if_idx and (len(lines[i]) - len(lines[i].lstrip(" "))) <= if_indent
    ]
    assert reachable_after_if_else, (
        "Nenhuma atribuição de session_state['metrics_ready'] = True vem depois do "
        "if/else de data_source na indentação correta — isso reproduz o bug em que "
        "escolher MapBiomas nunca chega a calcular/exibir as métricas (só funcionava "
        "para o GeoTIFF próprio)."
    )
