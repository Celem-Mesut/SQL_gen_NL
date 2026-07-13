"""
test_lineage_en_doc_export.py -- lineage cikarimi ve wiki-dokumantasyon
uretiminin birim testleri. Coklu-sema eslesmesi (her eslesmeye ayri ok),
VW_-oneki toleransi, terminal-view tespiti, ADO-uyumlu Mermaid sozdizimi
ve wiki-bundle yapisi dahil.
"""
import pytest

from conftest import make_df
from lineage import (
    build_full_lineage_mermaid,
    build_lineage_dot,
    build_lineage_index,
    build_lineage_mermaid,
    find_terminal_views,
    trace_lineage,
)
from doc_export import _wiki_page_name, build_stage_documentation, build_wiki_bundle
from sql_generator import generate_all_views


# ----------------------------------------------------------------------------
# Yardimci: iki asamali sahte index
# ----------------------------------------------------------------------------

@pytest.fixture
def two_stage_index():
    return {
        "sot.VW_PW_X":  {"direct_sources": ["RAW_OOST"], "target_table": "PW_X",
                          "stage": "Silver_to_GGM", "stage_order": 0},
        "gin.VW_DIM_X": {"direct_sources": ["PW_X"], "target_table": "DIM_X",
                          "stage": "GGM_to_Gold", "stage_order": 1},
    }


# ----------------------------------------------------------------------------
# Zincirleme / eslestirme
# ----------------------------------------------------------------------------

def test_keten_over_fasen_heen(two_stage_index):
    nodes, edges = trace_lineage("gin.VW_DIM_X", two_stage_index)
    assert nodes == {"RAW_OOST", "sot.VW_PW_X", "gin.VW_DIM_X"}
    assert ("RAW_OOST", "sot.VW_PW_X") in edges
    assert ("sot.VW_PW_X", "gin.VW_DIM_X") in edges


def test_vw_prefix_tolerantie():
    """'PW_X' ile 'VW_PW_X' ayni mantiksal tablo olarak eslesmeli."""
    index = {
        "sot.VW_PW_X":  {"direct_sources": ["RAW"], "target_table": "PW_X",
                          "stage": "s1", "stage_order": 0},
        "gin.VW_DIM_X": {"direct_sources": ["VW_PW_X"], "target_table": "DIM_X",
                          "stage": "s2", "stage_order": 1},
    }
    _, edges = trace_lineage("gin.VW_DIM_X", index)
    assert ("sot.VW_PW_X", "gin.VW_DIM_X") in edges


def test_meerdere_schemas_zelfde_tabelnaam_meerdere_pijlen():
    """Coklu-sema eslesmesi: 'ilk gorulen kazanir' YOK -- her eslesmeye ok."""
    index = {
        "sot.VW_PW_X":  {"direct_sources": ["RAW_O"], "target_table": "PW_X",
                          "stage": "s1", "stage_order": 0},
        "arch.VW_PW_X": {"direct_sources": ["RAW_W"], "target_table": "PW_X",
                          "stage": "s1", "stage_order": 0},
        "gin.VW_DIM_X": {"direct_sources": ["PW_X"], "target_table": "DIM_X",
                          "stage": "s2", "stage_order": 1},
    }
    _, edges = trace_lineage("gin.VW_DIM_X", index)
    assert ("sot.VW_PW_X", "gin.VW_DIM_X") in edges
    assert ("arch.VW_PW_X", "gin.VW_DIM_X") in edges
    assert ("RAW_O", "sot.VW_PW_X") in edges     # beide voorouders gevolgd
    assert ("RAW_W", "arch.VW_PW_X") in edges
    # Terminal-detectie: beide PW_X-views zijn "verbruikt"
    assert find_terminal_views(index) == ["gin.VW_DIM_X"]


def test_terminal_views(two_stage_index):
    assert find_terminal_views(two_stage_index) == ["gin.VW_DIM_X"]


# ----------------------------------------------------------------------------
# Mermaid: ADO-uyumluluk
# ----------------------------------------------------------------------------

def test_mermaid_ado_compatibel(two_stage_index):
    for code in (build_lineage_mermaid("gin.VW_DIM_X", two_stage_index),
                 build_full_lineage_mermaid(two_stage_index)):
        assert code.startswith("graph ")          # ADO 8.14: 'flowchart' NIET ondersteund
        assert "flowchart" not in code
        assert ":::" not in code                  # oude class-shorthand vermijden
        assert "classDef" in code
        assert "-->" in code


def test_mermaid_en_dot_zelfde_knopen(two_stage_index):
    """Graphviz-gorseli ve Mermaid-kodu ayni dugum kumesini gostermeli."""
    dot = build_lineage_dot("gin.VW_DIM_X", two_stage_index)
    mmd = build_lineage_mermaid("gin.VW_DIM_X", two_stage_index)
    for label in ("RAW_OOST", "sot.VW_PW_X", "gin.VW_DIM_X"):
        assert label in dot
        assert label in mmd


# ----------------------------------------------------------------------------
# build_lineage_index -- gercek uretim yolundan
# ----------------------------------------------------------------------------

def test_index_uit_echte_stages():
    silver = make_df([
        dict(source_schema="dbo", source_table="RAW_A", source_column="ID",
             target_schema="sot", target_table="PW_A", target_column="ID", target_datatype="INT"),
    ])
    gold = make_df([
        dict(source_schema="ggm", source_table="PW_A", source_column="ID",
             target_schema="gin", target_table="DIM_A", target_column="ID", target_datatype="INT"),
    ])
    index = build_lineage_index({"Silver_to_GGM": silver, "GGM_to_Gold": gold})
    assert "sot.VW_PW_A" in index and "gin.VW_DIM_A" in index
    assert index["sot.VW_PW_A"]["stage_order"] == 0
    assert index["gin.VW_DIM_A"]["stage_order"] == 1
    _, edges = trace_lineage("gin.VW_DIM_A", index)
    assert ("sot.VW_PW_A", "gin.VW_DIM_A") in edges   # sema farkina ragmen eslesti


# ----------------------------------------------------------------------------
# doc_export
# ----------------------------------------------------------------------------

def _entries_from(df, stage_name):
    results, _ = generate_all_views(df)
    entries = []
    for (ts, tt), item in results.items():
        g = df[(df["target_schema"] == ts) & (df["target_table"] == tt)]
        entries.append({"stage_name": stage_name, "view_data": item["view_data"],
                        "group_df": g, "view_key": f"{stage_name}::{ts}::{tt}"})
    return entries


def test_stage_document_bevat_geen_sql_en_geen_doeltype(simple_rows):
    df = make_df(simple_rows)
    entries = _entries_from(df, "s1")
    index = build_lineage_index({"s1": df})
    doc = build_stage_documentation("s1", entries, index, {})
    assert "```sql" not in doc                    # SQL bewust weggelaten
    assert "| Doeltype |" not in doc              # kolomtabel versimpeld
    assert "| Brontabel | Bronkolom | Brontype | Doelkolom |" in doc
    assert "Business toelichting nog niet ingevuld" in doc


def test_stage_document_met_toelichting(simple_rows):
    df = make_df(simple_rows)
    entries = _entries_from(df, "s1")
    index = build_lineage_index({"s1": df})
    doc = build_stage_documentation("s1", entries, index, {entries[0]["view_key"]: "Test-toelichting."})
    assert "Test-toelichting." in doc


def test_wiki_bundle_structuur(simple_rows):
    df = make_df(simple_rows)
    entries = _entries_from(df, "s1")
    index = build_lineage_index({"s1": df})
    bundle = build_wiki_bundle(entries, index, {})
    assert "Lineage-Overzicht.md" in bundle
    table_pages = [k for k in bundle if k != "Lineage-Overzicht.md"]
    assert len(table_pages) == 1
    overzicht = bundle["Lineage-Overzicht.md"]
    assert "```mermaid" in overzicht
    # Links: absolute wiki-paden
    assert "(/Lineage-Overzicht/" in overzicht
    assert "[← Terug naar het lineage-overzicht](/Lineage-Overzicht)" in bundle[table_pages[0]]


def test_wiki_page_name_sanitize():
    assert _wiki_page_name("sot.VW_PW_X") == "sot-VW_PW_X"
    assert "/" not in _wiki_page_name("a/b#c?d:e")
