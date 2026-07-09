"""
Testes da predição de anos futuros via cadeia de Markov
(_build_transition_matrix/_project_future_landcover, app.py) — ver
"Predição de anos futuros (cadeia de Markov)" no ROADMAP.md.
"""
import numpy as np
import pandas as pd
import pytest

import app


def test_build_transition_matrix_all_class1_to_class2():
    arr_2000 = np.full((4, 4), 1, dtype=np.uint8)
    arr_2010 = np.full((4, 4), 2, dtype=np.uint8)

    transition = app._build_transition_matrix([arr_2000, arr_2010], [2000, 2010])

    assert transition.loc[1, 2] == pytest.approx(1.0)
    assert transition.loc[1, 1] == pytest.approx(0.0)


def test_build_transition_matrix_unobserved_class_falls_back_to_identity():
    arr_2000 = np.full((4, 4), 1, dtype=np.uint8)
    arr_2010 = np.full((4, 4), 2, dtype=np.uint8)

    transition = app._build_transition_matrix([arr_2000, arr_2010], [2000, 2010])

    # Classe 2 nunca aparece como origem (só como destino) — assume
    # identidade (sem mudança) em vez de NaN/zero.
    assert transition.loc[2, 2] == pytest.approx(1.0)


def test_build_transition_matrix_aggregates_multiple_consecutive_pairs():
    arr_2000 = np.full((4, 4), 1, dtype=np.uint8)
    arr_2010 = np.full((4, 4), 1, dtype=np.uint8)
    arr_2020 = np.full((4, 4), 2, dtype=np.uint8)

    transition = app._build_transition_matrix([arr_2000, arr_2010, arr_2020], [2000, 2010, 2020])

    # Metade das transições observadas (2000->2010) ficou em classe 1, a
    # outra metade (2010->2020) foi para classe 2 — agregado, a linha da
    # classe 1 reflete os dois pares.
    assert transition.loc[1, 1] == pytest.approx(0.5)
    assert transition.loc[1, 2] == pytest.approx(0.5)


def test_build_transition_matrix_resamples_mismatched_shapes():
    arr_2000 = np.full((4, 4), 1, dtype=np.uint8)
    arr_2010 = np.full((8, 8), 2, dtype=np.uint8)  # resolução/extent diferente

    transition = app._build_transition_matrix([arr_2000, arr_2010], [2000, 2010])

    assert transition.loc[1, 2] == pytest.approx(1.0)


def test_build_transition_matrix_orders_by_year_regardless_of_input_order():
    arr_2000 = np.full((4, 4), 1, dtype=np.uint8)
    arr_2010 = np.full((4, 4), 2, dtype=np.uint8)

    # Passa os arrays fora de ordem — a função deve ordenar por `years`.
    transition = app._build_transition_matrix([arr_2010, arr_2000], [2010, 2000])

    assert transition.loc[1, 2] == pytest.approx(1.0)


def test_project_future_landcover_full_transition_one_step():
    transition_df = pd.DataFrame({1: [0.0, 0.0], 2: [1.0, 1.0]}, index=[1, 2])
    last_proportions = pd.Series({1: 1.0, 2: 0.0})

    result = app._project_future_landcover(transition_df, 2010, last_proportions, 10.0, [2020])

    assert result.loc[2020, 2] == pytest.approx(100.0, abs=0.5)
    assert result.loc[2020, 1] == pytest.approx(0.0, abs=0.5)


def test_project_future_landcover_identity_matrix_keeps_proportions_stable():
    transition_df = pd.DataFrame({1: [1.0, 0.0], 2: [0.0, 1.0]}, index=[1, 2])
    last_proportions = pd.Series({1: 0.7, 2: 0.3})

    result = app._project_future_landcover(transition_df, 2010, last_proportions, 10.0, [2020, 2030])

    for target_year in (2020, 2030):
        assert result.loc[target_year, 1] == pytest.approx(70.0, abs=0.5)
        assert result.loc[target_year, 2] == pytest.approx(30.0, abs=0.5)


def test_project_future_landcover_ignores_non_future_years():
    transition_df = pd.DataFrame({1: [1.0]}, index=[1])
    last_proportions = pd.Series({1: 1.0})

    result = app._project_future_landcover(transition_df, 2010, last_proportions, 10.0, [2000, 2010])

    assert result.empty


def test_project_future_landcover_sums_to_100_percent():
    transition_df = pd.DataFrame(
        {1: [0.6, 0.2], 2: [0.4, 0.8]}, index=[1, 2],
    )
    last_proportions = pd.Series({1: 0.5, 2: 0.5})

    result = app._project_future_landcover(transition_df, 2010, last_proportions, 10.0, [2015])

    assert result.loc[2015].sum() == pytest.approx(100.0, abs=0.01)
