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

ESLESTIRME KURALI (ONEMLI): Bir asamanin urettigi bir view, bir SONRAKI
asamada source_table olarak referans verildiginde, eslesme SADECE TABLO
ADINA gore yapilir -- source_schema/source_system/target_schema/
target_system TAMAMEN YOK SAYILIR. Yani Silver_to_GGM sayfasinda
target_table='PW_X' ureten bir view, GGM_to_Gold sayfasinda
source_table='PW_X' yazan HERHANGI bir satirla eslesir, sema/warehouse
isimleri farkli olsa BILE (orn. 'sot' vs 'ggm'). Bu, kullanicinin acik
talebidir: ortamda ayni mantiksal tabloya farkli semalarda referans
verilebiliyor, ama bu hala AYNI lineage zincirinin parcasidir.

RENKLENDIRME: Her node, ADINDA GECEN Medallion katmanina gore (Silver/GGM/
Gold/Bronze -- hem NL hem EN terimler) AYIRT EDICI ama birbiriyle UYUMLU bir
renk alir (bkz. _layer_style). Boylece bir Gold view'in soy agacinda Silver
ve GGM dugumlerini renklerinden aninda ayirt edebilirsiniz.
"""

from collections import OrderedDict

from sql_generator import generate_all_views, qualified_view_name


def _direct_sources(group_df):
    """Bir (target_schema, target_table) grubunun TUM satirlarindan,
    benzersiz source_table degerlerini cikarir (CSV sirasi korunur).
    NOT: source_schema/source_system kasten YOK SAYILIR -- eslestirme
    SADECE tablo adina gore yapilir (bkz. modul docstring'i)."""
    seen = OrderedDict()
    for _, row in group_df.iterrows():
        seen[row["source_table"]] = True
    return list(seen.keys())


def _normalize_table(table):
    """Tablo adini, 'VW_' onekini ATARAK normallestirir -- boylece
    'PW_X' ile 'VW_PW_X' AYNI mantiksal tablo olarak eslesir (kullanici
    bir sonraki asamada onek yazmayi unutsa bile zincir kirilmaz)."""
    return table[3:] if table.lower().startswith("vw_") else table


def build_lineage_index(stages):
    """Tum asamalardaki TUM view'lerin nitelikli adlarini ve dogrudan
    kaynaklarini (sadece tablo adi olarak) tek bir indekse cikarir.

    Donus: OrderedDict[qualified_name_str] -> {
        "direct_sources": [source_table_str, ...],  # SEMA/SYSTEM YOK
        "target_table": str,   # bu view'in HAM (CSV'deki) target_table degeri
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
                "target_table": target_table,
                "stage": stage_name,
            }
    return index


def _build_table_lookup(index):
    """index'teki her view icin, normallestirilmis target_table adindan
    qualified_name'e giden bir arama tablosu kurar. Birden fazla view AYNI
    tablo adina sahipse (farkli semalarda ayni isim), ILK GORULENI kullanir
    (CSV/sayfa sirasina gore) -- bu, coklu eslesme belirsizligini cozmenin
    en basit/ongorulebilir yoludur."""
    lookup = OrderedDict()
    for qname, info in index.items():
        key = _normalize_table(info["target_table"])
        if key not in lookup:
            lookup[key] = qname
    return lookup


def _resolve_match(source_table, table_lookup, exclude=None):
    """source_table adinin (sema/system yok sayilarak), index'teki BASKA
    bir view'in target_table'ina karsilik gelip gelmedigini kontrol eder.
    Esleserse o view'in qualified adini, eslesmezse None doner."""
    key = _normalize_table(source_table)
    matched = table_lookup.get(key)
    if matched and matched != exclude:
        return matched
    return None


def find_terminal_views(index):
    """Index'teki view'lerden, HICBIR BASKA view tarafindan kaynak olarak
    KULLANILMAYANLARI (yani her zincirin EN SONUNDAKI / "nihai" katmandaki
    tablolari) dondurur.

    NEDEN: Bir Gold view'in soy agaci, zaten kendi GGM/Silver atalarini
    icinde gosteriyor -- bu yuzden GGM'nin KENDI ayri bir sekmesi/diyagrami
    GEREKSIZ TEKRARDIR. Sadece zincirin sonundaki (hicbir sonraki asama
    tarafindan tuketilmeyen) view'leri sekme olarak gosterip, ara
    katmanlari SADECE o sekmelerin diyagrami ICINDE gosteriyoruz."""
    table_lookup = _build_table_lookup(index)
    consumed = set()
    for qname, info in index.items():
        for source_table in info["direct_sources"]:
            matched = _resolve_match(source_table, table_lookup, exclude=qname)
            if matched:
                consumed.add(matched)
    return [q for q in index if q not in consumed]


def trace_lineage(qname, index, table_lookup=None, _visited=None):
    """qname icin TUM atalarini (ancestors) recursive olarak bulur.

    Donus: (nodes, edges)
        nodes: qualified-name string'lerinin kumesi (view'ler VE leaf kaynaklar)
        edges: (kaynak, hedef) ciftlerinin kumesi
    """
    if table_lookup is None:
        table_lookup = _build_table_lookup(index)
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

    for source_table in info["direct_sources"]:
        matched = _resolve_match(source_table, table_lookup, exclude=qname)
        src_label = matched or source_table
        nodes.add(src_label)
        edges.add((src_label, qname))
        if matched:
            sub_nodes, sub_edges = trace_lineage(matched, index, table_lookup, _visited)
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
