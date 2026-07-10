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

RENKLENDIRME (ONEMLI): Renkler, node ADININ ICERIGINE (orn. "silver"/"ggm"/
"gold" kelimeleri gecip gecmedigine) BAKILARAK DEGIL, view'in HANGI ASAMA
TARAFINDAN URETILDIGINE (gercek pipeline sirasina) gore atanir. Bu, sema/
warehouse adlandirma kurali ne olursa olsun (orn. kullanicinin gercek
ortamindaki "sot"/"gin" gibi katmani belli etmeyen sema adlari) HER ZAMAN
dogru ve tutarli renklendirme saglar. asamalar, kullanicinin Excel'deki
sayfa SIRASINA gore numaralandirilir (ilk sayfa = en erken/0. seviye); ham
kaynak tablolar (hicbir asama tarafindan uretilmemis "leaf" node'lar) en
erken seviyeden bir ONCEKI seviyeye yerlestirilir. Bkz. _assign_levels.
"""

from collections import OrderedDict

from sql_generator import generate_all_views, qualified_view_name

# Kronolojik sira ile: en erken seviye (orn. Silver/ham kaynak) -> en son
# seviye (orn. Gold/hedef). (fillcolor, bordercolor) ciftleri.
_PALETTE = [
    ("#F6E2A8", "#C9A227"),   # sari tonlar -- en erken seviye
    ("#BFD7EF", "#5B85B8"),   # mavi tonlar -- ara seviye(ler)
    ("#C9E4D3", "#5A9B76"),   # yesil tonlar -- en son/hedef seviye
    ("#F3D2B3", "#C97A3D"),   # turuncu tonlar -- ek ara seviye (4+ katman icin)
    ("#E3C6E8", "#9B6BAE"),   # mor tonlar -- ek ara seviye (5+ katman icin)
]
_FALLBACK_COLOR = ("#EDEAE3", "#9C9890")  # notr gri -- palet tukenirse


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
        "target_table": str,    # bu view'in HAM (CSV'deki) target_table degeri
        "stage": stage_name,
        "stage_order": int,     # stages sozlugundeki SIRA (0 = ilk sayfa/asama)
    }
    """
    index = OrderedDict()
    for stage_order, (stage_name, df) in enumerate(stages.items()):
        results, _ = generate_all_views(df, use_create_or_alter=True, add_go=False)
        for (target_schema, target_table), item in results.items():
            view_data = item["view_data"]
            qname = qualified_view_name(view_data, brackets=False)
            group_df = df[(df["target_schema"] == target_schema) & (df["target_table"] == target_table)]
            index[qname] = {
                "direct_sources": _direct_sources(group_df),
                "target_table": target_table,
                "stage": stage_name,
                "stage_order": stage_order,
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


def _assign_levels(nodes, index):
    """Her node'a, GERCEK PIPELINE SIRASINA dayanan bir "seviye" (level)
    atar:
        - index'te bulunan (yani bir asama tarafindan URETILEN) node'lar
          icin: o asamanin stage_order'i kullanilir.
        - index'te BULUNMAYAN (ham/leaf kaynak tablolar -- hicbir asama
          tarafindan uretilmemis) node'lar icin: mevcut en erken
          stage_order'dan BIR ONCEKI seviyeye yerlestirilir (cunku
          kavramsal olarak "ilk asamanin GIRDISI" konumundadirlar).

    Donus: dict[node] -> raw_level (int, kucuk=daha erken/yukari akis)
    """
    stage_orders = [index[n]["stage_order"] for n in nodes if n in index]
    earliest = min(stage_orders) if stage_orders else 0
    levels = {}
    for n in nodes:
        if n in index:
            levels[n] = index[n]["stage_order"]
        else:
            levels[n] = earliest - 1
    return levels


def _level_to_color(level, sorted_distinct_levels):
    """Bir node'un ham seviyesini (level), o lineage alt-grafiginde
    GORULEN BENZERSIZ seviyelerin SIRALI listesindeki KONUMUNA gore bir
    renge cevirir. Boylece kac farkli "katman" varsa (2, 3, 4...), her biri
    PALETTE'den AYIRT EDICI bir renk alir; en erken katman SARI, en son
    (hedef) katman YESIL olur, aradakiler MAVI/TURUNCU/MOR ile doldurulur."""
    position = sorted_distinct_levels.index(level)
    total = len(sorted_distinct_levels)

    if total == 1:
        return _PALETTE[2]  # tek katman -- hedefin kendisi -- yesil
    if position == 0:
        return _PALETTE[0]  # en erken katman -- sari
    if position == total - 1:
        return _PALETTE[2]  # en son katman (hedef) -- yesil

    # Aradaki katmanlar: PALETTE'deki orta renkleri (indeks 1, 3, 4, ...)
    # sirayla kullanir; palet tukenirse notr griye doner.
    middle_palette = [_PALETTE[1]] + _PALETTE[3:]
    middle_index = position - 1
    if middle_index < len(middle_palette):
        return middle_palette[middle_index]
    return _FALLBACK_COLOR


def build_lineage_dot(qname, index, direction="LR"):
    """qname icin soy agacini Graphviz DOT dili metnine cevirir."""
    nodes, edges = trace_lineage(qname, index)
    levels = _assign_levels(nodes, index)
    sorted_distinct_levels = sorted(set(levels.values()))

    lines = [
        "digraph G {",
        f'  rankdir="{direction}";',
        '  bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, margin="0.15,0.1"];',
        '  edge [color="#9C9890"];',
    ]
    for n in sorted(nodes):
        fill, border = _level_to_color(levels[n], sorted_distinct_levels)
        penwidth = "2.2" if n == qname else "1"
        escaped = n.replace('"', '\\"')
        lines.append(
            f'  "{n}" [label="{escaped}", fillcolor="{fill}", fontcolor="#262624", '
            f'color="{border}", penwidth={penwidth}];'
        )
    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


def _render_mermaid(nodes, edges, levels, focus=None, direction="LR"):
    """Ortak Mermaid uretici -- hem tekil soy agaci (build_lineage_mermaid)
    hem tum-katman grafigi (build_full_lineage_mermaid) icin.

    AZURE DEVOPS UYUMLULUGU (onemli): Azure DevOps Wiki, Mermaid'in eski
    surumunu (8.14.0) kullanir ve 'flowchart' anahtar kelimesini DESTEKLEMEZ
    -- 'graph' kullanilmalidir. Sinif atamasi da ':::' kisayolu yerine ayri
    'class <id> <cls>' satirlariyla yapilir (eski surumlerde en genis
    destege sahip soz dizimi).

    Mermaid dugum ID'leri alfasayisal olmak zorunda oldugundan (nitelikli
    view adlari nokta/koseli-parantez icerebilir), her dugum icin sentetik
    bir ID (n0, n1, ...) uretilir; GERCEK ad sadece dugumun ETIKETI (label)
    olarak, tirnak icinde gosterilir."""
    sorted_distinct_levels = sorted(set(levels.values()))
    mermaid_direction = "TD" if direction.upper() in ("TB", "TD") else direction.upper()

    sorted_nodes = sorted(nodes)
    node_ids = {n: f"n{i}" for i, n in enumerate(sorted_nodes)}

    # Her benzersiz renk (fill,border) cifti icin bir classDef -- ayni
    # renkteki dugumler ayni sinifi paylasir, kod daha kisa/okunakli olur.
    color_to_class = {}
    classdef_lines = []
    class_assignments = {}  # cls -> [node_id, ...]
    for n in sorted_nodes:
        color = _level_to_color(levels[n], sorted_distinct_levels)
        if color not in color_to_class:
            cls = f"lvl{len(color_to_class)}"
            color_to_class[color] = cls
            fill, border = color
            classdef_lines.append(
                f"    classDef {cls} fill:{fill},stroke:{border},color:#262624,stroke-width:1px;"
            )
        class_assignments.setdefault(color_to_class[color], []).append(node_ids[n])

    lines = [f"graph {mermaid_direction}"] + classdef_lines
    for n in sorted_nodes:
        nid = node_ids[n]
        label = n.replace('"', "'")
        lines.append(f'    {nid}["{label}"]')
    for src, dst in sorted(edges):
        lines.append(f"    {node_ids[src]} --> {node_ids[dst]}")
    for cls, ids in class_assignments.items():
        lines.append(f"    class {','.join(ids)} {cls};")
    if focus and focus in node_ids:
        lines.append(f"    style {node_ids[focus]} stroke-width:2.5px")

    return "\n".join(lines)


def build_lineage_mermaid(qname, index, direction="LR"):
    """qname icin soy agacini Mermaid 'graph' sozdizimine cevirir --
    build_lineage_dot ile AYNI dugum kumesini, kenarlari ve renk/seviye
    mantigini (_assign_levels, _level_to_color, _PALETTE) kullanir, boylece
    Graphviz gorseli ile Mermaid ciktisi HER ZAMAN tutarli kalir.

    Azure DevOps Wiki (ve GitHub/GitLab wiki'leri) Mermaid kod bloklarini
    dogrudan render eder -- cikti, bir ```mermaid kod bloguna oldugu gibi
    yapistirilabilir (bkz. _render_mermaid'daki ADO-uyumluluk notlari)."""
    nodes, edges = trace_lineage(qname, index)
    levels = _assign_levels(nodes, index)
    return _render_mermaid(nodes, edges, levels, focus=qname, direction=direction)


def build_full_lineage_mermaid(index, direction="LR"):
    """TUM asamalardaki TUM view'leri ve ham kaynak tablolarini TEK bir
    Mermaid grafiginde birlestirir (Silver -> ... -> Gold, tek gorsel).
    Renk/seviye mantigi tekil diyagramlarla birebir aynidir."""
    table_lookup = _build_table_lookup(index)
    nodes = set(index.keys())
    edges = set()
    for qname, info in index.items():
        for source_table in info["direct_sources"]:
            matched = _resolve_match(source_table, table_lookup, exclude=qname)
            src_label = matched or source_table
            nodes.add(src_label)
            edges.add((src_label, qname))
    levels = _assign_levels(nodes, index)
    return _render_mermaid(nodes, edges, levels, direction=direction)
