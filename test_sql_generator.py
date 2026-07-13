"""
test_sql_generator.py -- SQL uretim cekirdeginin birim testleri.

Bu dosyadaki senaryolarin cogu, gelistirme sirasinda ELLE test edilmis
gercek durumlarin kalici halidir: JOIN zinciri, UNION dallari, eksik-kolon
NULL doldurma, alias kurali, filter-only satirlar, CAST mantigi, Business
Key, kismi union_group hatasi, preflight kontrolleri.
"""
import pytest

from conftest import make_df
from sql_generator import (
    ValidationError,
    build_business_key_select_line,
    generate_all_views,
    parse_business_key_input,
    preflight_validate,
    render_view_sql,
)


# ----------------------------------------------------------------------------
# Temel uretim
# ----------------------------------------------------------------------------

def test_simple_view_basic_structure(simple_rows):
    df = make_df(simple_rows)
    results, warnings = generate_all_views(df)
    assert warnings == []
    assert len(results) == 1
    sql = results[("Gold", "Y")]["sql"]
    assert "CREATE OR ALTER VIEW [Gold].[VW_Y]" in sql
    assert "[ID] AS [ID]" in sql
    assert "[NAAM] AS [Naam]" in sql
    assert sql.rstrip().endswith("GO")


def test_create_view_zonder_or_alter_en_zonder_go(simple_rows):
    df = make_df(simple_rows)
    results, _ = generate_all_views(df, use_create_or_alter=False, add_go=False)
    sql = results[("Gold", "Y")]["sql"]
    assert sql.startswith("CREATE VIEW ")
    assert "CREATE OR ALTER" not in sql
    assert not sql.rstrip().endswith("GO")


def test_deterministisch_zelfde_input_zelfde_sql(simple_rows):
    """Projenin temel garantisi: ayni girdi -> ayni SQL."""
    df1, df2 = make_df(simple_rows), make_df(simple_rows)
    sql1 = generate_all_views(df1)[0][("Gold", "Y")]["sql"]
    sql2 = generate_all_views(df2)[0][("Gold", "Y")]["sql"]
    assert sql1 == sql2


# ----------------------------------------------------------------------------
# Alias / tablo oneki kurali
# ----------------------------------------------------------------------------

def test_single_source_geen_alias_prefix(simple_rows):
    sql = generate_all_views(make_df(simple_rows))[0][("Gold", "Y")]["sql"]
    assert "[X].[ID]" not in sql  # tek kaynak: prefix YOK
    assert "AS [X]" not in sql


def test_join_met_alias_prefix():
    rows = [
        dict(source_schema="Silver", source_table="A", source_column="ID",
             target_schema="Gold", target_table="Y", target_column="ID", target_datatype="INT"),
        dict(source_schema="Silver", source_table="B", source_column="ID2",
             target_schema="Gold", target_table="Y", target_column="ID2", target_datatype="INT",
             join_type="LEFT", join_condition="[A].[ID] = [B].[ID2]"),
    ]
    sql = generate_all_views(make_df(rows))[0][("Gold", "Y")]["sql"]
    assert "[A].[ID] AS [ID]" in sql          # coklu kaynak: prefix VAR
    assert "LEFT JOIN [Silver].[B] AS [B]" in sql
    assert "ON [A].[ID] = [B].[ID2]" in sql


def test_join_zonder_condition_geeft_groepsfout():
    rows = [
        dict(source_schema="Silver", source_table="A", source_column="ID",
             target_schema="Gold", target_table="Y", target_column="ID", target_datatype="INT"),
        dict(source_schema="Silver", source_table="B", source_column="ID2",
             target_schema="Gold", target_table="Y", target_column="ID2", target_datatype="INT"),
    ]
    results, warnings = generate_all_views(make_df(rows))
    assert results == {}
    assert len(warnings) == 1
    assert warnings[0]["target_table"] == "Y"
    assert "join_condition" in warnings[0]["message"]
    assert warnings[0]["row_indices"] == [0, 1]


# ----------------------------------------------------------------------------
# CAST / transformation / WHERE
# ----------------------------------------------------------------------------

def test_cast_alleen_bij_verschillend_datatype():
    rows = [
        dict(source_schema="S", source_table="T", source_column="A", source_datatype="INT",
             target_schema="G", target_table="Y", target_column="A", target_datatype="INT"),
        dict(source_schema="S", source_table="T", source_column="B", source_datatype="DATETIME2",
             target_schema="G", target_table="Y", target_column="B", target_datatype="DATE"),
        dict(source_schema="S", source_table="T", source_column="C", source_datatype="",
             target_schema="G", target_table="Y", target_column="C", target_datatype="INT"),
    ]
    sql = generate_all_views(make_df(rows))[0][("G", "Y")]["sql"]
    assert "[A] AS [A]" in sql and "CAST([A]" not in sql            # zelfde type: geen CAST
    assert "CAST([B] AS DATE) AS [B]" in sql                        # verschillend: CAST
    assert "[C] AS [C]" in sql and "CAST([C]" not in sql            # leeg brontype: geen CAST


def test_transformation_met_en_zonder_src_placeholder():
    rows = [
        dict(source_schema="S", source_table="T", source_column="NAAM",
             target_schema="G", target_table="Y", target_column="NaamUpper",
             target_datatype="NVARCHAR(100)", transformation="UPPER({src})"),
        # {src}'siz transformation -> kaynak kolon tamamen yok sayilir (NULL-kolon deseni)
        dict(source_schema="S", source_table="T", source_column="NAAM",
             target_schema="G", target_table="Y", target_column="NieuweKolom",
             target_datatype="NVARCHAR(50)", transformation="CAST(NULL AS NVARCHAR(50))"),
    ]
    sql = generate_all_views(make_df(rows))[0][("G", "Y")]["sql"]
    assert "UPPER([NAAM]) AS [NaamUpper]" in sql
    assert "CAST(NULL AS NVARCHAR(50)) AS [NieuweKolom]" in sql


def test_where_condities_gecombineerd_met_and():
    rows = [
        dict(source_schema="S", source_table="T", source_column="A",
             target_schema="G", target_table="Y", target_column="A", target_datatype="INT",
             where_condition="{src} IS NOT NULL"),
        dict(source_schema="S", source_table="T", source_column="B",
             target_schema="G", target_table="Y", target_column="B", target_datatype="INT",
             where_condition="{src} > 0"),
    ]
    sql = generate_all_views(make_df(rows))[0][("G", "Y")]["sql"]
    assert "([A] IS NOT NULL)" in sql
    assert "([B] > 0)" in sql
    assert "AND" in sql


def test_filter_only_rij_voegt_geen_kolom_toe():
    rows = [
        dict(source_schema="S", source_table="T", source_column="A",
             target_schema="G", target_table="Y", target_column="A", target_datatype="INT"),
        dict(source_schema="S", source_table="T", source_column="EINDDATUM",
             target_schema="G", target_table="Y", target_column="", target_datatype="",
             where_condition="{src} IS NULL"),
    ]
    results, warnings = generate_all_views(make_df(rows))
    sql = results[("G", "Y")]["sql"]
    assert warnings == []
    assert "[EINDDATUM] AS" not in sql          # SELECT'e girmedi
    assert "([EINDDATUM] IS NULL)" in sql       # WHERE'e girdi
    assert results[("G", "Y")]["column_count"] == 1


# ----------------------------------------------------------------------------
# target_system: 2-delige naam + commentaarregel
# ----------------------------------------------------------------------------

def test_target_system_alleen_als_commentaar():
    rows = [dict(source_schema="S", source_table="T", source_column="A",
                 target_schema="G", target_table="Y", target_column="A",
                 target_datatype="INT", target_system="Gold_WH")]
    sql = generate_all_views(make_df(rows))[0][("G", "Y")]["sql"]
    assert sql.startswith("-- Doel Warehouse/Lakehouse: Gold_WH")
    assert "CREATE OR ALTER VIEW [G].[VW_Y]" in sql     # 2-delig
    assert "[Gold_WH].[G].[VW_Y]" not in sql            # NIET 3-delig


def test_source_system_geeft_3_delige_bron():
    rows = [dict(source_system="GGM_WH", source_schema="ggm", source_table="T",
                 source_column="A", target_schema="G", target_table="Y",
                 target_column="A", target_datatype="INT")]
    sql = generate_all_views(make_df(rows))[0][("G", "Y")]["sql"]
    assert "FROM [GGM_WH].[ggm].[T]" in sql


# ----------------------------------------------------------------------------
# UNION ALL
# ----------------------------------------------------------------------------

def _union_rows(groups=("1", "2", "3")):
    rows = []
    for i, g in enumerate(groups):
        rows.append(dict(source_schema="S", source_table=f"BRON_{i}", source_column="ID",
                         target_schema="G", target_table="Y", target_column="ID",
                         target_datatype="INT", union_group=g))
    return rows


def test_union_all_drie_takken():
    sql = generate_all_views(make_df(_union_rows()))[0][("G", "Y")]["sql"]
    assert sql.count("UNION ALL") == 2
    for i in range(3):
        assert f"FROM [S].[BRON_{i}]" in sql


def test_union_ontbrekende_kolom_wordt_null_cast():
    rows = [
        dict(source_schema="S", source_table="OOST", source_column="ID",
             target_schema="G", target_table="Y", target_column="ID", target_datatype="INT", union_group="1"),
        dict(source_schema="S", source_table="OOST", source_column="OMS",
             target_schema="G", target_table="Y", target_column="Omschrijving",
             target_datatype="NVARCHAR(100)", union_group="1"),
        # Tak 2 heeft GEEN Omschrijving -> automatisch CAST(NULL AS NVARCHAR(100))
        dict(source_schema="S", source_table="WEST", source_column="ID_W",
             target_schema="G", target_table="Y", target_column="ID", target_datatype="INT", union_group="2"),
    ]
    sql = generate_all_views(make_df(rows))[0][("G", "Y")]["sql"]
    assert "CAST(NULL AS NVARCHAR(100)) AS [Omschrijving]" in sql


def test_union_group_deels_ingevuld_geeft_fout():
    rows = _union_rows(groups=("1", "2", ""))
    results, warnings = generate_all_views(make_df(rows))
    assert results == {}
    assert "union_group" in warnings[0]["message"]


def test_union_zelfde_groep_zonder_join_condition_geeft_hint():
    """Gercek kullanici hatasi: uc bron, HEPSI union_group=1 -> JOIN sanilir."""
    rows = _union_rows(groups=("1", "1", "1"))
    results, warnings = generate_all_views(make_df(rows))
    assert results == {}
    assert "union_group" in warnings[0]["message"]   # ipucu metni mevcut
    assert "VERSCHILLENDE" in warnings[0]["message"]


def test_lege_union_group_gedraagt_zich_als_vanouds(simple_rows):
    """Geriye donuk uyumluluk: union_group hic yoksa UNION uretilmez."""
    sql = generate_all_views(make_df(simple_rows))[0][("Gold", "Y")]["sql"]
    assert "UNION" not in sql


# ----------------------------------------------------------------------------
# Business Key / manuele kolommen
# ----------------------------------------------------------------------------

def test_business_key_parsing_en_render(simple_rows):
    df = make_df(simple_rows)
    results, _ = generate_all_views(df)
    view_data = results[("Gold", "Y")]["view_data"]
    col_map = {c["target_column"]: c["expr"] for c in view_data["columns"]}

    parts, errors = parse_business_key_input('"OOST", ID, Naam', col_map)
    assert errors == []
    line = build_business_key_select_line("BK", parts)
    assert "CONCAT('OOST'" in line and "AS [BK]" in line

    sql = render_view_sql(view_data, extra_columns=[{"name": "BK", "parts": parts, "raw_text": '"OOST", ID, Naam'}])
    # Manuele kolom staat VOORAAN in de SELECT
    assert sql.index("[BK]") < sql.index("[ID] AS [ID]")


def test_business_key_onbekende_kolom_geeft_fout(simple_rows):
    df = make_df(simple_rows)
    results, _ = generate_all_views(df)
    col_map = {c["target_column"]: c["expr"] for c in results[("Gold", "Y")]["view_data"]["columns"]}
    parts, errors = parse_business_key_input("BestaatNiet", col_map)
    assert errors != []


# ----------------------------------------------------------------------------
# preflight_validate
# ----------------------------------------------------------------------------

def test_preflight_schone_data_geeft_geen_issues(simple_rows):
    assert preflight_validate(make_df(simple_rows)) == []


def test_preflight_vangt_alle_bekende_problemen():
    rows = [
        dict(source_schema="Silver", source_table="A", source_column="ID",
             target_schema="Gold", target_table="Y", target_column="ID", target_datatype="INT"),
        # rij 3: target_datatype ontbreekt
        dict(source_schema="Silver", source_table="A", source_column="X1",
             target_schema="Gold", target_table="Y", target_column="K2", target_datatype=""),
        # rij 4: filter-only zonder where_condition
        dict(source_schema="Silver", source_table="A", source_column="X2",
             target_schema="Gold", target_table="Y", target_column="", target_datatype=""),
        # rij 5: ongeldige join_type + ontbrekende join_condition
        dict(source_schema="Silver", source_table="B", source_column="X3",
             target_schema="Gold", target_table="Y", target_column="K3",
             target_datatype="INT", join_type="LEFTT"),
        # rij 6: lege source_column + {scr}-typo + union_group deels
        dict(source_schema="Silver", source_table="A", source_column="",
             target_schema="Gold", target_table="Z", target_column="K",
             target_datatype="INT", transformation="UPPER({scr})", union_group="1"),
        # rij 7: zelfde Z, union_group leeg
        dict(source_schema="Silver", source_table="C", source_column="Y1",
             target_schema="Gold", target_table="Z", target_column="K2",
             target_datatype="INT", union_group=""),
    ]
    issues = preflight_validate(make_df(rows))
    kolommen = {i["kolom"] for i in issues}
    assert {"target_datatype", "where_condition", "join_type",
            "join_condition", "source_column", "transformation", "union_group"} <= kolommen
    # Excel-rijnummers kloppen (header=1, data vanaf 2)
    assert any(i["excel_rij"] == 3 and i["kolom"] == "target_datatype" for i in issues)
    assert any(i["excel_rij"] == 5 and i["kolom"] == "join_type" for i in issues)


def test_preflight_blokkeert_upload_niet():
    """Regressie: rij-niveau problemen mogen het INLADEN niet meer blokkeren
    (vroeger gooide _clean_and_validate een ValidationError op het hele bestand)."""
    rows = [dict(source_schema="", source_table="A", source_column="ID",
                 target_schema="Gold", target_table="Y", target_column="ID",
                 target_datatype="INT")]
    df = make_df(rows)          # mag NIET raisen
    assert len(df) == 1
    issues = preflight_validate(df)
    assert any(i["kolom"] == "source_schema" for i in issues)
