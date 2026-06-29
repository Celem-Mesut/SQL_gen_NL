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

RENKLENDIRME: Her node, ADINDA GECEN Medallion katmanina gore (Silver/GGM/
Gold/Bronze -- hem NL hem EN terimler) AYIRT EDICI ama birbiriyle UYUMLU bir
renk alir (bkz. _layer_style). Boylece bir Gold view'in soy agacinda Silver
ve GGM dugumlerini renklerinden aninda ayirt edebilirsiniz.
"""

from collections import OrderedDict

from sql_generator import generate_all_views, qualified_view_name


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


def _resolve_match(system, schema, table, index, exclude=None):
    """(system, schema, table) uclusunun, index'teki BASKA bir view'e
    karsilik gelip gelmedigini kontrol eder. Esleserse o view'in qualified
    adini, eslesmezse None doner."""
    candidates = [_qkey(system, schema, table), _qkey("", schema, table)]
    return next((k for k in candidates if k in index and k != exclude), None)


def find_terminal_views(index):
    """Index'teki view'lerden, HICBIR BASKA view tarafindan kaynak olarak
    KULLANILMAYANLARI (yani her zincirin EN SONUNDAKI / "nihai" katmandaki
    tablolari) dondurur.

    NEDEN: Bir Gold view'in soy agaci, zaten kendi GGM/Silver atalarini
    icinde gosteriyor -- bu yuzden GGM'nin KENDI ayri bir sekmesi/diyagrami
    GEREKSIZ TEKRARDIR (kullanicinin belirttigi sorun). Sadece zincirin
    sonundaki (hicbir sonraki asama tarafindan tuketilmeyen) view'leri
    sekme olarak gosterip, ara katmanlari SADECE o sekmelerin diyagrami
    ICINDE gosteriyoruz."""
    consumed = set()
    for qname, info in index.items():
        for system, schema, table in info["direct_sources"]:
            matched = _resolve_match(system, schema, table, index, exclude=qname)
            if matched:
                consumed.add(matched)
    return [q for q in index if q not in consumed]


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
        matched = _resolve_match(system, schema, table, index, exclude=qname)
        src_label = matched or _qkey(system, schema, table)
        nodes.add(src_label)
        edges.add((src_label, qname))
        if matched:
            sub_nodes, sub_edges = trace_lineage(matched, index, _visited)
            nodes |= sub_nodes
            edges |= sub_edges

    return nodes, edges


def _layer_style(node_name, is_target=False):
    """Node adinda gecen Medallion katmanina (Silver/GGM/Gold/Bronze -- hem
    NL hem EN terimler) gore uyumlu ama AYIRT EDICI bir renk cifti
    (fillcolor, bordercolor) doner. Oduncu (focus) node, AYNI renk ailesinde
    kalip sadece daha kalin bir cizgiyle (penwidth) vurgulanir -- yeni bir
    renk EKLEMEZ, kullanicinin "her seviye icin bir renk yeterli" istegine
    uygun."""
    name_lower = node_name.lower()
    if "goud" in name_lower or "gold" in name_lower:
        fill, border = "#C9E4D3", "#5A9B76"   # yesil tonlar -- Gold
    elif "ggm" in name_lower:
        fill, border = "#BFD7EF", "#5B85B8"   # mavi tonlar -- GGM
    elif "zilver" in name_lower or "silver" in name_lower:
        fill, border = "#F6E2A8", "#C9A227"   # sari tonlar -- Silver
    elif "brons" in name_lower or "bronze" in name_lower:
        fill, border = "#E3C6A8", "#A97142"   # bronz tonlar -- Bronze
    else:
        fill, border = "#EDEAE3", "#9C9890"   # bilinmeyen katman -- notr gri
    penwidth = "2.2" if is_target else "1"
    return fill, border, penwidth


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
        fill, border, penwidth = _layer_style(n, is_target=(n == qname))
        escaped = n.replace('"', '\\"')
        lines.append(
            f'  "{n}" [label="{escaped}", fillcolor="{fill}", fontcolor="#262624", '
            f'color="{border}", penwidth={penwidth}];'
        )
    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)
