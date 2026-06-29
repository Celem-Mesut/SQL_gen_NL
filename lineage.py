"""
:material/hub: lineage.py
-----------
Tum asamalardaki (stages) view'lerin birbirine olan bagimliligini (lineage)
cikarir ve her view icin tam soy agacini Graphviz DOT dilinde bir metne
cevirir. HARICI BIR KUTUPHANEYE GEREK YOKTUR (graphviz pip paketi DAHIL) --
DOT metnini dogrudan string olarak uretiriz; st.graphviz_chart() bu metni
tarayicida (d3-graphviz ile) render eder, sunucuda sistem binary'si gerekmez.

NOT: Bu dosyada hicbir st.* cagrisi YOKTUR (saf arka uc mantigi) -- yukaridaki
:material/hub: isareti, sadece app.py'deki "Lineage" sayfasinin ikonuyla
GORSEL/KAVRAMSAL eslesme amaclidir, kod calisma zamaninda bir etkisi yoktur.
"""

from collections import OrderedDict

from sql_generator import generate_all_views, qualified_view_name

# Renkler -- .streamlit/config.toml'daki Claude.ai temasiyla tutarli
_COLOR_TARGET = "#C15F3C"      # Crail (vurgu) -- bu sekmenin oduncu tablosu
_COLOR_KNOWN_VIEW = "#EAE7DD"  # Pampas/Cloudy arasi -- baska bir asamanin urettigi ara view
_COLOR_LEAF = "#FFFFFF"        # beyaz -- ham/bilinmeyen kaynak (baska bir CSV asamasi tarafindan uretilmemis)


def _direct_sources(group_df):
    """Bir (target_schema, target_table) grubunun TUM satirlarindan,
    benzersiz (source_system, source_schema, source_table) uclulerini
    cikarir (CSV sirasi korunur)."""
    seen = OrderedDict()
    for _, row in group_df.iterrows():
        key = (row["source_system"], row["source_schema"], row["source_table"])
        seen[key] = True
    return list(seen.keys())


def _qkey(system, schema, table):
    """qualified_view_name ile AYNI formatta bir arama anahtari uretir
    (boylece bir source ucluusunun, baska bir asamanin uretttigi bir view'e
    karsilik gelip gelmedigini index'te arayabiliriz)."""
    parts = [p for p in (system, schema, table) if p]
    return ".".join(parts)


def build_lineage_index(stages):
    """Tum asamalardaki TUM view'lerin nitelikli adlarini ve dogrudan
    kaynaklarini tek bir indekse cikarir.

    Donus: OrderedDict[qualified_name_str] -> {
        "direct_sources": [(system, schema, table), ...],
        "stage": stage_name,
    }
    """
    index = OrderedDict()
    for stage_name, df in stages.items():
        results, _ = generate_all_views(df, use_create_or_alter=True, add_go=False)
        for (target_schema, target_table), item in results.items():
            view_data = item["view_data"]
            qname = qualified_view_name(view_data, brackets=False)
            group_df = df[(df["target_schema"] == target_schema) & (df["target_table"] == target_table)]
            index[qname] = {
                "direct_sources": _direct_sources(group_df),
                "stage": stage_name,
            }
    return index


def trace_lineage(qname, index, _visited=None):
    """qname icin TUM atalarini (ancestors) recursive olarak bulur.

    Donus: (nodes, edges)
        nodes: qualified-name string'lerinin kumesi (view'ler VE leaf kaynaklar)
        edges: (kaynak, hedef) ciftlerinin kumesi
    """
    if _visited is None:
        _visited = set()
    nodes = {qname}
    edges = set()

    if qname in _visited:
        return nodes, edges  # dongu koruması (teorik olarak olmamali ama guvenlik icin)
    _visited.add(qname)

    info = index.get(qname)
    if not info:
        return nodes, edges  # leaf -- bizim urettigimiz bir view degil

    for system, schema, table in info["direct_sources"]:
        candidates = [_qkey(system, schema, table), _qkey("", schema, table)]
        matched = next((k for k in candidates if k in index and k != qname), None)
        src_label = matched or _qkey(system, schema, table)
        nodes.add(src_label)
        edges.add((src_label, qname))
        if matched:
            sub_nodes, sub_edges = trace_lineage(matched, index, _visited)
            nodes |= sub_nodes
            edges |= sub_edges

    return nodes, edges


def build_lineage_dot(qname, index, direction="LR"):
    """qname icin soy agacini Graphviz DOT dili metnine cevirir."""
    nodes, edges = trace_lineage(qname, index)

    lines = [
        "digraph G {",
        f'  rankdir="{direction}";',
        '  bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, margin="0.15,0.1"];',
        '  edge [color="#9C9890"];',
    ]
    for n in sorted(nodes):
        if n == qname:
            fill, font = _COLOR_TARGET, "white"
        elif n in index:
            fill, font = _COLOR_KNOWN_VIEW, "#262624"
        else:
            fill, font = _COLOR_LEAF, "#262624"
        escaped = n.replace('"', '\\"')
        lines.append(f'  "{n}" [label="{escaped}", fillcolor="{fill}", fontcolor="{font}", color="#9C9890"];')
    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)
