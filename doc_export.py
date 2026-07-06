"""
doc_export.py
-------------
Her fase (bijv. Silver_to_GGM, GGM_to_Gold) icin AYRI bir okunakli Markdown
dokumani uretir -- kopyalanip/indirilip bir wiki'ye (orn. Azure DevOps Wiki)
yapistirilmak icin. Bu modulde hicbir Streamlit kodu YOKTUR; tum
fonksiyonlar zaten hazirlanmis veriyi alip SAF metin ureten fonksiyonlardir
(app.py bunlari cagirir).

Sablon yapisi (her view icin):
    1. Baslik/meta bilgi (view adi, faz, warehouse, kaynak tablolar) -- OTOMATIK
    2. Business toelichting -- MANUEL (kullanicidan, bos birakilabilir)
    3. Kolomtoewijzing tablosu (bron+hedef kolon, sadece ISIMLER) -- OTOMATIK
    4. Filters/join/union mantigi -- OTOMATIK
    5. Lineage (Mermaid kodu) -- OTOMATIK

BILINCLI OLARAK DISINDA BIRAKILAN (kullanicinin acik talebi):
    - Uretilen SQL betigi -- zaten Home sayfasinda mevcut, burada tekrarı
      goz yorar/kafa karistirir.
    - Doeltype ve transformatie kolonlari -- kolon tablosunda gorsel gurultu
      yaratiyordu, sadece isim eslesmesi (bron->hedef) yeterli.
    - Ham CSV/Excel satir dokumu -- Sjablonen'den de kaldirilmisti.
    - Tum fazlari TEK bir dokumanda birlestirme -- her faz kendi AYRI
      dokumanini/indirme dosyasini alir (bkz. build_stage_documentation).
"""

from datetime import datetime

from lineage import build_lineage_mermaid
from sql_generator import qualified_view_name


def _format_column_table(group_df):
    """group_df'teki (bir view'e ait tum satirlar) SADECE target_column
    dolu olan satirlardan bir Markdown tablosu uretir -- filtre-only
    satirlar (target_column bos) burada DEGIL, Filters bolumunde gosterilir.
    SADECE brontabel/bronkolom/brontip/doelkolom gosterilir -- doeltype ve
    transformatie kasten disarida birakildi (kullanicinin acik talebi:
    gorsel gurultu azaltmak, SQL zaten teknik ek olarak Home'da mevcut)."""
    rows = group_df[group_df["target_column"] != ""]
    if rows.empty:
        return "_Geen kolommen._"
    lines = [
        "| Brontabel | Bronkolom | Brontype | Doelkolom |",
        "|---|---|---|---|",
    ]
    for _, row in rows.iterrows():
        src_type = row["source_datatype"] or "—"
        lines.append(
            f"| {row['source_table']} | {row['source_column']} | {src_type} "
            f"| {row['target_column']} |"
        )
    return "\n".join(lines)


def _format_rules_section(group_df):
    """WHERE / JOIN / UNION bilgisini, wiki-okuyucusu icin duz metin madde
    listesine cevirir (ham SQL degil, kisa aciklama)."""
    lines = []

    joins = group_df[(group_df["join_type"] != "") & (group_df["join_condition"] != "")]
    for _, row in joins.iterrows():
        lines.append(
            f"- **JOIN** ({row['join_type'] or 'INNER'}) met `{row['source_table']}` "
            f"op: `{row['join_condition']}`"
        )

    wheres = group_df[group_df["where_condition"] != ""]
    for _, row in wheres.iterrows():
        cond = row["where_condition"].replace("{src}", f"[{row['source_column']}]")
        lines.append(f"- **Filter** op `{row['source_table']}`: `{cond}`")

    if (group_df["union_group"] != "").any():
        branch_labels = list(dict.fromkeys(g for g in group_df["union_group"] if g))
        branch_descriptions = []
        for g in branch_labels:
            tables = list(dict.fromkeys(group_df[group_df["union_group"] == g]["source_table"]))
            branch_descriptions.append(f"tak {g} ({', '.join(tables)})")
        lines.append(
            f"- **UNION ALL** van {len(branch_labels)} takken -- " + "; ".join(branch_descriptions)
        )

    return "\n".join(lines) if lines else "_Geen extra filters, joins of union._"


def build_view_markdown(stage_name, view_data, group_df, lineage_index, purpose_text=""):
    """Een enkele (target_schema, target_table) view naar een Markdown-
    sectie omzet, volgens het sjabloon beschreven in de moduledocstring.
    Bevat GEEN gegenereerde SQL -- die is al zichtbaar op de Home-pagina;
    hier zou het alleen visuele ruis toevoegen (expliciet verzoek gebruiker)."""
    qname = qualified_view_name(view_data, brackets=False)
    sources = list(dict.fromkeys(group_df["source_table"]))

    lines = [f"## `{qualified_view_name(view_data)}`", ""]
    lines.append(f"- **Fase:** {stage_name}")
    if view_data.get("target_system"):
        lines.append(f"- **Warehouse/Lakehouse:** {view_data['target_system']}")
    lines.append(f"- **Bronnen:** {', '.join(f'`{s}`' for s in sources)}")
    lines.append("")

    if purpose_text and purpose_text.strip():
        lines.append(f"> **Business toelichting:** {purpose_text.strip()}")
    else:
        lines.append("> _Business toelichting nog niet ingevuld._")
    lines.append("")

    lines.append("### Kolomtoewijzing")
    lines.append(_format_column_table(group_df))
    lines.append("")

    lines.append("### Filters, joins & union-logica")
    lines.append(_format_rules_section(group_df))
    lines.append("")

    if qname in lineage_index:
        lines.append("### Lineage")
        lines.append("```mermaid")
        lines.append(build_lineage_mermaid(qname, lineage_index))
        lines.append("```")
        lines.append("")

    lines.append("\n---\n")

    return "\n".join(lines)


def build_stage_documentation(stage_name, view_entries, lineage_index, purposes):
    """EEN fase (bijv. 'Silver_to_GGM') naar een OP ZICHZELF STAAND Markdown-
    document omzet. app.py roept dit APART per fase aan, zodat elke fase
    een eigen document/downloadbestand krijgt (expliciet verzoek gebruiker
    -- niet meer één groot gecombineerd document)."""
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Mapping-documentatie — {stage_name}",
        f"_Automatisch gegenereerd door csv2sql op {generated_at}._",
        "",
    ]
    for entry in view_entries:
        purpose = purposes.get(entry["view_key"], "")
        lines.append(build_view_markdown(
            entry["stage_name"], entry["view_data"], entry["group_df"],
            lineage_index, purpose_text=purpose,
        ))
    return "\n".join(lines)
