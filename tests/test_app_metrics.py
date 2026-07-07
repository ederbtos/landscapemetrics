"""
Testes das funções de suporte ao modo multi-arquivo (upload de vários
GeoTIFFs comparados entre si): extração de ano do nome do arquivo, cálculo
de métricas por classe compartilhado entre os caminhos de fonte única e
múltipla, gráfico de comparação, relatório HTML para impressão/PDF e
métricas de nível de paisagem (diversidade/agregação, ver 09_business_rules.md
e ROADMAP.md para o que fica de fora por não ter suporte no PyLandStats).
"""
import numpy as np
import pytest

import app


@pytest.mark.parametrize(
    "filename,expected_year",
    [
        ("Corte_255_2000.tif", 2000),
        ("Corte_255_2010.tif", 2010),
        ("raster_2023_v2.tiff", 2023),
        ("area_sem_ano.tif", None),
        ("255.tif", None),  # número de 3 dígitos não é um ano plausível (19xx/20xx)
    ],
)
def test_extract_year_from_filename(filename, expected_year):
    assert app._extract_year_from_filename(filename) == expected_year


def test_compute_class_metrics_uses_mapbiomas_legend_names():
    arr = np.full((10, 10), 15, dtype="uint8")  # 15 = Pastagem
    ls, class_metrics_df_sub = app._compute_class_metrics(arr, (30, 30))

    assert list(class_metrics_df_sub.index) == ["Pastagem"]
    assert "total_area" in class_metrics_df_sub.columns
    assert ls is not None


def test_compute_class_metrics_reports_progress_per_metric_and_flags_slow_one():
    arr = np.full((10, 10), 15, dtype="uint8")
    progress_calls = []
    messages = []

    app._compute_class_metrics(
        arr, (30, 30),
        notify=messages.append,
        on_metric_progress=lambda i, total, label: progress_calls.append((i, total, label)),
    )

    assert len(progress_calls) == len(app.METRICS_INFO)
    assert progress_calls[0][0] == 0
    assert progress_calls[-1][0] == len(app.METRICS_INFO) - 1
    assert all(total == len(app.METRICS_INFO) for _, total, _ in progress_calls)
    # euclidean_nearest_neighbor_mn (SLOW_METRIC_NAME) está em standby (ver
    # METRICS_INFO) — só checa o aviso especial quando ela estiver ativa de
    # novo, para não quebrar o teste enquanto ela ficar comentada.
    if app.SLOW_METRIC_NAME in {name for name, *_ in app.METRICS_INFO}:
        assert any("distância entre todas as manchas" in m for m in messages)


def test_compute_class_metrics_pads_small_arrays():
    arr = np.full((2, 2), 15, dtype="uint8")
    messages = []

    ls, class_metrics_df_sub = app._compute_class_metrics(arr, (30, 30), notify=messages.append)

    assert any("pequena" in m for m in messages)
    assert not class_metrics_df_sub.empty


def test_compute_landscape_metrics_matches_manual_diversity_formulas():
    rng = np.random.default_rng(1)
    small = rng.choice([3, 4, 15, 24], size=(20, 20), p=[0.35, 0.25, 0.3, 0.1]).astype("uint8")
    arr = np.repeat(np.repeat(small, 10, axis=0), 10, axis=1)
    ls, _ = app._compute_class_metrics(arr, (30, 30))

    values = app._compute_landscape_metrics(ls)

    assert values["patch_richness"] == 4
    assert values["shannon_evenness_index"] == pytest.approx(
        values["shannon_diversity_index"] / np.log(4), rel=1e-6
    )
    assert 0 < values["simpson_diversity_index"] < 1
    assert values["simpson_evenness_index"] == pytest.approx(
        values["simpson_diversity_index"] / (1 - 1 / 4), rel=1e-6
    )
    # Vêm direto do PyLandStats — só confirma que a chamada foi bem-sucedida.
    for key in ("contagion", "effective_mesh_size", "patch_density", "edge_density", "landscape_shape_index"):
        assert values[key] is not None


def test_render_landscape_metrics_does_not_raise():
    values = {"shannon_diversity_index": 1.3, "patch_richness": 4, "contagion": 41.7}
    app._render_landscape_metrics(values)  # só garante que não levanta exceção


def _fake_result(label, year, fill_values, resolution=(30, 30)):
    arr = np.random.default_rng(42).choice(fill_values, size=(15, 15)).astype("uint8")
    ls, class_metrics_df_sub = app._compute_class_metrics(arr, resolution)
    return {
        "label": label,
        "year": year,
        "np_arr_mb": arr,
        "ls": ls,
        "class_metrics_df_sub": class_metrics_df_sub,
        "reprojected_tif_bytes": None,
    }


def test_render_comparison_chart_returns_figure_with_one_line_per_class():
    results = [
        _fake_result("a_2000.tif", 2000, [3, 4, 15]),
        _fake_result("a_2010.tif", 2010, [3, 4, 15, 24]),
    ]

    fig = app._render_comparison_chart(results, "total_area", "Área Total (ha)")

    assert fig is not None
    ax = fig.axes[0]
    assert 1 <= len(ax.get_lines()) <= len(app.CATEGORICAL_PALETTE)


def test_render_comparison_chart_returns_none_for_missing_metric():
    results = [_fake_result("a.tif", None, [3])]

    fig = app._render_comparison_chart(results, "metric_que_nao_existe", "Nada")

    assert fig is None


def test_build_html_report_contains_per_file_tables_and_comparison_images():
    results = [
        _fake_result("a_2000.tif", 2000, [3, 4, 15]),
        _fake_result("a_2010.tif", 2010, [3, 4, 15, 24]),
    ]

    html = app._build_html_report(results, 300, "Meu raster (GeoTIFF)")

    assert "a_2000.tif" in html
    assert "a_2010.tif" in html
    assert "<img" in html  # gráficos comparativos embutidos em base64
    assert "<table" in html.lower()


def test_build_html_report_single_file_has_no_comparison_images():
    results = [_fake_result("unico.tif", None, [3, 4])]

    html = app._build_html_report(results, None, "Meu raster (GeoTIFF)")

    assert "unico.tif" in html
    assert "<img" not in html


# --- _compute_fingerprint (identidade de submissão para o cache em
# db.metric_results, ver docstring da função e do módulo db.py) ---


def test_compute_fingerprint_same_file_bytes_produce_same_fingerprint():
    fp1 = app._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"conteudo-do-tif")
    fp2 = app._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"conteudo-do-tif")
    assert fp1 == fp2


def test_compute_fingerprint_different_file_bytes_produce_different_fingerprint():
    fp1 = app._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"arquivo-a")
    fp2 = app._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"arquivo-b")
    assert fp1 != fp2


def test_compute_fingerprint_whole_raster_differs_from_point_mode_for_same_file():
    fp_whole = app._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"x", whole_raster=True)
    fp_point = app._compute_fingerprint(
        "Meu raster (GeoTIFF)", tif_bytes=b"x", point_lonlat=(-47.9, -15.8), buffer_dist=5000,
        whole_raster=False,
    )
    assert fp_whole != fp_point


def test_compute_fingerprint_mapbiomas_point_rounding_absorbs_jitter():
    fp1 = app._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.929211, -15.780099), buffer_dist=5000,
    )
    fp2 = app._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.929212, -15.780098), buffer_dist=5000,
    )
    assert fp1 == fp2


def test_compute_fingerprint_different_point_produces_different_fingerprint():
    fp1 = app._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.9292, -15.7801), buffer_dist=5000,
    )
    fp2 = app._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-46.0, -14.0), buffer_dist=5000,
    )
    assert fp1 != fp2


def test_compute_fingerprint_different_buffer_produces_different_fingerprint():
    fp1 = app._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.9292, -15.7801), buffer_dist=1000,
    )
    fp2 = app._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.9292, -15.7801), buffer_dist=5000,
    )
    assert fp1 != fp2
