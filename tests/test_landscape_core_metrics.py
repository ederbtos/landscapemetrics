"""
Testes de `_extract_year_from_filename`/`_compute_class_metrics`/
`_compute_landscape_metrics`/`_compute_fingerprint` em
`backend/app/services/landscape_core.py` — ver 09_business_rules.md e
ROADMAP.md para o que fica de fora das métricas por não ter suporte no
PyLandStats.

Portadas de `tests/test_app_metrics.py` (app.py Streamlit, removido). Esse
arquivo também testava `_render_landscape_metrics`/`_render_comparison_chart`/
`_build_html_report` (matplotlib + montagem de HTML para impressão/PDF) —
essas três NUNCA foram extraídas para `landscape_core.py` e não têm
equivalente no backend/frontend novo (que renderiza gráficos no cliente via
Chart.js) — funcionalidade de exportar relatório HTML/gráfico de comparação
multi-arquivo com essas imagens embutidas fica descoberta por este refactor,
não é escopo dele recriar. Ver ROADMAP.md.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import landscape_core


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
    assert landscape_core._extract_year_from_filename(filename) == expected_year


def test_compute_class_metrics_uses_mapbiomas_legend_names():
    arr = np.full((10, 10), 15, dtype="uint8")  # 15 = Pastagem
    ls, class_metrics_df_sub = landscape_core._compute_class_metrics(arr, (30, 30))

    assert list(class_metrics_df_sub.index) == ["Pastagem"]
    assert "total_area" in class_metrics_df_sub.columns
    assert ls is not None


def test_compute_class_metrics_reports_progress_per_metric_and_flags_slow_one():
    arr = np.full((10, 10), 15, dtype="uint8")
    progress_calls = []
    messages = []

    landscape_core._compute_class_metrics(
        arr, (30, 30),
        notify=messages.append,
        on_metric_progress=lambda i, total, label: progress_calls.append((i, total, label)),
    )

    assert len(progress_calls) == len(landscape_core.METRICS_INFO)
    assert progress_calls[0][0] == 0
    assert progress_calls[-1][0] == len(landscape_core.METRICS_INFO) - 1
    assert all(total == len(landscape_core.METRICS_INFO) for _, total, _ in progress_calls)
    # euclidean_nearest_neighbor_mn (SLOW_METRIC_NAME) está em standby (ver
    # METRICS_INFO) — só checa o aviso especial quando ela estiver ativa de
    # novo, para não quebrar o teste enquanto ela ficar comentada.
    if landscape_core.SLOW_METRIC_NAME in {name for name, *_ in landscape_core.METRICS_INFO}:
        assert any("distância entre todas as manchas" in m for m in messages)


def test_compute_class_metrics_pads_small_arrays():
    arr = np.full((2, 2), 15, dtype="uint8")
    messages = []

    ls, class_metrics_df_sub = landscape_core._compute_class_metrics(arr, (30, 30), notify=messages.append)

    assert any("pequena" in m for m in messages)
    assert not class_metrics_df_sub.empty


def test_compute_landscape_metrics_matches_manual_diversity_formulas():
    rng = np.random.default_rng(1)
    small = rng.choice([3, 4, 15, 24], size=(20, 20), p=[0.35, 0.25, 0.3, 0.1]).astype("uint8")
    arr = np.repeat(np.repeat(small, 10, axis=0), 10, axis=1)
    ls, _ = landscape_core._compute_class_metrics(arr, (30, 30))

    values = landscape_core._compute_landscape_metrics(ls)

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


# --- _compute_fingerprint (identidade de submissão para o cache em
# backend/app/db/metric_results.py, ver docstring da função) ---


def test_compute_fingerprint_same_file_bytes_produce_same_fingerprint():
    fp1 = landscape_core._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"conteudo-do-tif")
    fp2 = landscape_core._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"conteudo-do-tif")
    assert fp1 == fp2


def test_compute_fingerprint_different_file_bytes_produce_different_fingerprint():
    fp1 = landscape_core._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"arquivo-a")
    fp2 = landscape_core._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"arquivo-b")
    assert fp1 != fp2


def test_compute_fingerprint_whole_raster_differs_from_point_mode_for_same_file():
    fp_whole = landscape_core._compute_fingerprint("Meu raster (GeoTIFF)", tif_bytes=b"x", whole_raster=True)
    fp_point = landscape_core._compute_fingerprint(
        "Meu raster (GeoTIFF)", tif_bytes=b"x", point_lonlat=(-47.9, -15.8), buffer_dist=5000,
        whole_raster=False,
    )
    assert fp_whole != fp_point


def test_compute_fingerprint_mapbiomas_point_rounding_absorbs_jitter():
    fp1 = landscape_core._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.929211, -15.780099), buffer_dist=5000,
    )
    fp2 = landscape_core._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.929212, -15.780098), buffer_dist=5000,
    )
    assert fp1 == fp2


def test_compute_fingerprint_different_point_produces_different_fingerprint():
    fp1 = landscape_core._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.9292, -15.7801), buffer_dist=5000,
    )
    fp2 = landscape_core._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-46.0, -14.0), buffer_dist=5000,
    )
    assert fp1 != fp2


def test_compute_fingerprint_different_buffer_produces_different_fingerprint():
    fp1 = landscape_core._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.9292, -15.7801), buffer_dist=1000,
    )
    fp2 = landscape_core._compute_fingerprint(
        "MapBiomas (Google Earth Engine)", point_lonlat=(-47.9292, -15.7801), buffer_dist=5000,
    )
    assert fp1 != fp2
