"""
csv2sql - Streamlit Arayuzu (cok sayfali surum)
-------------------------------------------------
Kaynak -> hedef kolon mapping bilgisini iceren bir CSV veya cok-sayfali bir
Excel dosyasi yukleyin, Microsoft Fabric Warehouse (T-SQL) icin
CREATE OR ALTER VIEW betiklerini otomatik olarak uretin, istege bagli olarak
her view icin bir veya daha fazla MANUEL kolon (Business Key, kontrol
kolonu, vb.) ekleyin ve sonuclari indirin.

Sayfalar (sol kenar cubugundaki butonlarla gezilir):
    Home                 -> dosya yukleme + hemen altinda uretilen view'ler
    Lineage              -> her tablo icin, tum asamalar arasi soy agaci diyagrami
    Instellingen         -> CREATE OR ALTER VIEW / GO ayarlari
    Documentatie & hulp  -> sablon indirme + SSS

NOT: Kullanici arayuzu (butonlar, basliklar, hata mesajlari) TAMAMEN
HOLLANDACA'dir -- bu, programin son kullanicisi icindir. Bu Python
dosyasindaki KOD YORUMLARI (gelistirici notlari) Turkce kalmistir.

IKON KURALI: Tum ikonlar Google Material Symbols (`:material/isim:`)
kullanir -- emoji DEGIL. Bu, hem `icon=` parametresi destekleyen
widget'larda (st.button, st.download_button) hem de metin/markdown icine
gomulu olarak (st.title, st.caption, expander/tab etiketleri) calisir.

Calistirmak icin:
    pip install -r requirements.txt
    streamlit run app.py
"""

from datetime import datetime

import streamlit as st

from sql_generator import (
    ValidationError,
    generate_all_views,
    load_mapping_csv,
    load_mapping_excel,
    parse_business_key_input,
    qualified_view_name,
    render_view_sql,
)
from lineage import build_lineage_dot, build_lineage_index, find_terminal_views

st.set_page_config(page_title="CSV/Excel -> T-SQL View Generator", page_icon=":material/code:", layout="wide")

# ----------------------------------------------------------------------------
# Sayfa yonlendirme (routing) altyapisi
# ----------------------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "stages" not in st.session_state:
    st.session_state.stages = {}
if "load_info" not in st.session_state:
    st.session_state.load_info = None

st.markdown(
    """
    <style>
    /* -------------------------------------------------------------------
       Tipografi: Space Grotesk (basliklar) + Inter (govde) + JetBrains
       Mono (kod). Streamlit'in sistem varsayilan fontu yerine bilincli
       bir font ciftlemesi -- veri muhendisligi/SQL uretim aracina uygun,
       teknik ama okunakli bir kimlik.
       ------------------------------------------------------------------- */
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"], [data-testid="stAppViewContainer"] {
        font-family: 'Inter', -apple-system, sans-serif;
    }
    h1, h2, h3, [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3,
    [data-testid="stSidebar"] h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        letter-spacing: -0.01em;
        font-weight: 600 !important;
    }
    code, pre, [data-testid="stCodeBlock"] *, .stCodeBlock * {
        font-family: 'JetBrains Mono', 'Courier New', monospace !important;
    }

    /* -------------------------------------------------------------------
       Streamlit imzasini gizle (footer + Deploy butonu).
       ------------------------------------------------------------------- */
    footer { visibility: hidden; }
    [data-testid="stToolbar"] [data-testid="stAppDeployButton"] { display: none; }

    /* -------------------------------------------------------------------
       Palet -- her renge NET bir rol verildi, rastgele dagilim yok:
         #fb8b24 (princeton-orange) -> primaryColor, birincil eylem
         #0f4c5c (dark-teal)        -> sidebar (ayri navigasyon zonu)
         #5f0f40 (crimson-violet)   -> baslik tipografisi (h1/h2/h3)
         #e36414 (autumn-leaf)      -> yapisal cerceveler (kart/metric)
         #9a031e (deep-crimson)     -> yikici eylemler (verwijderen)
       ------------------------------------------------------------------- */
    h1, h2, h3, [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        letter-spacing: -0.01em;
        font-weight: 600 !important;
        color: #5f0f40 !important;
    }
    code, pre, [data-testid="stCodeBlock"] *, .stCodeBlock * {
        font-family: 'JetBrains Mono', 'Courier New', monospace !important;
    }

    [data-testid="stExpander"] {
        border: 1px solid #e36414 !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 3px rgba(38, 38, 36, 0.05);
        overflow: hidden;
    }
    [data-testid="stExpander"] summary {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 500;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #e36414;
        border-radius: 8px;
        padding: 14px 18px;
    }
    [data-testid="stMetricLabel"] { font-family: 'Inter', sans-serif; opacity: 0.7; }
    [data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif; }

    /* Fase-/tab-schakelaars (Home-output + Lineage): actief = princeton-orange
       (primaryColor via Streamlit's eigen 'primary' knop-stijl), inactief =
       autumn-leaf omkaderd. */
    [class*="_stage_nav"] button {
        font-size: 1.05rem !important;
        font-family: 'Space Grotesk', sans-serif !important;
        font-weight: 600 !important;
        padding: 0.9rem 1.2rem !important;
        border-radius: 10px !important;
    }
    [class*="_stage_nav"] button[kind="secondary"] {
        border-color: #e36414 !important;
    }

    /* Sidebar: dark-teal achtergrond -- eigen navigatiezone, duidelijk
       gescheiden van de crème inhoud. Tekst/iconen worden licht. */
    [data-testid="stSidebar"] {
        background: #0f4c5c;
        border-right: none;
    }
    [data-testid="stSidebar"] * { color: #F1EDE6 !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 { color: #F1EDE6 !important; }
    [data-testid="stSidebar"] hr { border-color: rgba(241, 237, 230, 0.25); }
    [data-testid="stSidebar"] button[kind="secondary"] {
        background: rgba(241, 237, 230, 0.08);
        border-color: rgba(241, 237, 230, 0.3);
    }
    [data-testid="stSidebar"] button p {
        transition: font-weight 0.15s ease, opacity 0.15s ease;
    }
    [data-testid="stSidebar"] button:hover p {
        font-weight: 700 !important;
    }
    [data-testid="stSidebar"] button:active p {
        opacity: 0.7;
    }

    /* Sjabloon-onizleme tabelleri zijn uitgeschakeld -- deze regel blijft
       staan voor het geval een dataframe elders nog getoond wordt. */
    [data-testid="stDataFrame"] {
        border: 1px solid #e36414 !important;
        border-radius: 8px !important;
        overflow: hidden;
    }

    /* Instellingen-kaart: instellingen niet los in een lege pagina laten
       zweven, maar in een afgebakend kader. */
    .st-key-settings_card {
        border: 1px solid #e36414;
        border-radius: 12px;
        padding: 24px 28px;
        background: #FFFFFF;
        max-width: 640px;
    }

    /* Verwijder-knoppen (destructieve actie) -- deep-crimson. */
    button[title*="Verwijder"], .st-key-delete_btn button {
        border-color: #9a031e !important;
        color: #9a031e !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

NAV_PAGES = [
    ("Home", ":material/home:"),
    ("Lineage", ":material/hub:"),
    ("Instellingen", ":material/settings:"),
    ("Documentatie & hulp", ":material/menu_book:"),
]


def _stage_icon(stage_name):
    """Geeft een passend symbool terug op basis van de naam van de fase
    (Medallion-architectuur: Bronze/Silver/Gold -- zowel NL als EN termen
    worden herkend). Onbekende namen krijgen een generiek vraagteken-symbool."""
    name = stage_name.lower()
    if "goud" in name or "gold" in name:
        return ":material/schema:"
    if "zilver" in name or "silver" in name:
        return ":material/account_tree:"
    if "brons" in name or "bronze" in name:
        return ":material/apps:"
    return ":material/indeterminate_question_box:"


with st.sidebar:
    st.markdown("### :material/join_right: csv2sql")
    st.divider()
    for _name, _icon in NAV_PAGES:
        _active = st.session_state.page == _name
        if st.button(
            f"{_icon}  {_name}", key=f"nav_{_name}",
            type="primary" if _active else "secondary", width='stretch',
        ):
            st.session_state.page = _name
            st.rerun()


# ----------------------------------------------------------------------------
# Manuel kolon UI'i (eski tek-Business-Key formunun genellestirilmis hali)
# ----------------------------------------------------------------------------

def _append_suggestion(parts_key, sugg_key):
    """on_click callback: secilen kolonu, SCRIPT GOVDESI yeniden calismadan
    ONCE parca metnine ekler. ONEMLI: bunu 'if button: st.session_state[...] =
    ...' seklinde DOGRUDAN yazarsan 'cannot be modified after the widget ...
    is instantiated' hatasi alirsin -- cunku o widget bu script calismasinda
    ZATEN render edildi. Callback'ler ise script govdesinden ONCE calisir,
    bu yuzden orada session_state'i degistirmek serbesttir."""
    picked = st.session_state.get(sugg_key, "")
    if picked:
        current = st.session_state.get(parts_key, "")
        sep = ", " if current.strip() else ""
        st.session_state[parts_key] = current + sep + picked


def render_manual_columns_ui(view_key, col_map):
    """Birden fazla manuel olarak tanimlanmis kolon yonetir (Business Key,
    kontrol kolonu, ya da herhangi bir amacla). Her giriste SABIT/KALICI bir
    kimlik (id) kullanilir -- INDEX (0,1,2...) DEGIL -- cunku bir oge
    silindiginde diger ogelerin index'i kayar ve index'e bagli widget
    key'leri eski degerlerini "sizdirir" (yanlislikla baska bir ogenin
    verisini gosterir). Kalici id, silme sonrasi kalan ogelerin kendi
    widget'larini DOGRU sekilde korumasini saglar.

    Donus: extra_columns listesi (render_view_sql'e dogrudan verilebilir)."""
    col_options = list(col_map.keys())
    state_key = f"manual_cols_{view_key}"
    counter_key = f"{state_key}_counter"
    if state_key not in st.session_state:
        st.session_state[state_key] = []
    if counter_key not in st.session_state:
        st.session_state[counter_key] = 0

    to_delete = None
    for entry in st.session_state[state_key]:
        uid = entry["id"]
        name_key = f"{state_key}_{uid}_name"
        parts_key = f"{state_key}_{uid}_parts"
        sugg_key = f"{state_key}_{uid}_sugg"

        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            c1.text_input("Kolomnaam", key=name_key, placeholder="Regio_Sleutel")
            c2.text_input(
                "Onderdelen", key=parts_key,
                placeholder='"OOST", PersoonID, Geboortedatum',
            )

            sug_col, sug_btn, del_btn = st.columns([3, 1, 1])
            sug_col.selectbox(
                "Kolom toevoegen", options=[""] + col_options, key=sugg_key,
                label_visibility="collapsed",
            )
            sug_btn.button(
                "Toevoegen", key=f"{state_key}_{uid}_suggbtn",
                on_click=_append_suggestion, args=(parts_key, sugg_key), icon=":material/add:",
            )
            if del_btn.button("Verwijder", key=f"{state_key}_{uid}_del", icon=":material/delete:"):
                to_delete = uid

    if to_delete is not None:
        st.session_state[state_key] = [e for e in st.session_state[state_key] if e["id"] != to_delete]
        st.rerun()

    if st.button("Kolom toevoegen", key=f"{state_key}_add", icon=":material/add:"):
        st.session_state[counter_key] += 1
        st.session_state[state_key].append({"id": st.session_state[counter_key]})
        st.rerun()

    extra_columns = []
    for entry in st.session_state[state_key]:
        uid = entry["id"]
        name = st.session_state.get(f"{state_key}_{uid}_name", "")
        raw_parts = st.session_state.get(f"{state_key}_{uid}_parts", "")
        if not name or not raw_parts.strip():
            continue
        parts, errors = parse_business_key_input(raw_parts, col_map)
        if errors:
            for e in errors:
                st.error(e)
        elif parts:
            extra_columns.append({"name": name, "parts": parts})

    return extra_columns


# ----------------------------------------------------------------------------
# Output: bir asamayi (CSV/Excel sayfasi) ureten ve gosteren fonksiyon
# ----------------------------------------------------------------------------

def render_stage(stage_name, df, use_create_or_alter, add_go):
    """Bir asamaya (CSV veya bir Excel sayfasi) ait tum view'leri uretir,
    her biri icin manuel-kolon formuyla birlikte gosterir. Donus: o asamada
    uretilen tum nihai SQL metinlerinin listesi."""
    results, warnings = generate_all_views(df, use_create_or_alter=use_create_or_alter, add_go=add_go)

    if warnings:
        st.warning(
            "De volgende groepen zijn overgeslagen omdat ze fouten bevatten:\n\n"
            + "\n\n".join(f"- {w}" for w in warnings)
        )

    if not results:
        st.error("In deze fase kon geen enkele geldige view worden gegenereerd.")
        return []

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Aantal gegenereerde views", len(results))
    col_b.metric("Totaal aantal kolommen (rijen)", len(df))
    col_c.metric("Unieke brontabellen", df[["source_schema", "source_table"]].drop_duplicates().shape[0])

    final_sqls = []
    for idx, ((target_schema, target_table), item) in enumerate(results.items()):
        view_data = item["view_data"]
        view_key = f"{stage_name}::{target_schema}::{target_table}"
        col_map = {c["target_column"]: c["expr"] for c in view_data["columns"]}

        title = f":material/table_view: {qualified_view_name(view_data)}"

        # Eerste view standaard open -- gebruiker ziet direct dat er SQL-
        # inhoud en een "kolom toevoegen" formulier achter de titel zit,
        # zonder eerst te hoeven klikken om dat te ontdekken.
        with st.expander(title, expanded=(idx == 0)):
            meta_bits = [f":material/table_rows: {item['column_count']} kolommen"]
            if view_data.get("target_system"):
                meta_bits.append(f":material/database: {view_data['target_system']}")
            st.caption("&nbsp;&nbsp;·&nbsp;&nbsp;".join(meta_bits))

            st.caption(":material/extension: Handmatig toegevoegde kolommen (bijv. Business Key, controlekolom, ...)")
            extra_columns = render_manual_columns_ui(view_key, col_map)

            try:
                final_sql = render_view_sql(view_data, extra_columns=extra_columns)
            except ValidationError as e:
                st.error(str(e))
                final_sql = item["sql"]

            st.code(final_sql, language="sql")
            st.download_button(
                "Download deze view", data=final_sql.encode("utf-8"),
                file_name=(
                    (f"{view_data['target_system']}." if view_data.get("target_system") else "")
                    + f"{qualified_view_name(view_data, brackets=False)}.sql"
                ), mime="text/sql",
                key=f"dl_{view_key}", icon=":material/download:",
            )
        final_sqls.append(final_sql)

    if final_sqls:
        combined = "\n\n".join(final_sqls)
        st.download_button(
            f"Download alle views van fase '{stage_name}'",
            data=combined.encode("utf-8"),
            file_name=f"{stage_name}.sql", mime="text/sql",
            key=f"dl_stage_{stage_name}", icon=":material/download:",
        )
    return final_sqls


# ============================================================================
# PAGINA: Home
# ============================================================================
if st.session_state.page == "Home":
    st.title(":material/join_right: CSV/Excel → T-SQL View Generator")
    st.caption(
        "Upload een CSV-bestand (één fase) of een Excel-bestand met meerdere "
        "bladen (elk blad een eigen fase, bijv. Silver→GGM, GGM→Gold); voor elke "
        "doeltabel wordt automatisch een `CREATE OR ALTER VIEW`-script gegenereerd."
    )

    uploaded_file = st.file_uploader("Upload uw CSV- of Excel-bestand (.xlsx)", type=["csv", "xlsx"])

    if uploaded_file is not None:
        is_excel = uploaded_file.name.lower().endswith(".xlsx")
        if is_excel:
            try:
                stages, load_errors = load_mapping_excel(uploaded_file)
            except Exception as e:
                st.error(f"Excel-bestand kon niet worden gelezen: {e}")
                stages, load_errors = {}, {}
            if load_errors:
                st.warning(
                    "De volgende bladen zijn overgeslagen wegens een validatiefout:\n\n"
                    + "\n\n".join(f"**{name}**: {msg}" for name, msg in load_errors.items())
                )
            if not stages and not load_errors:
                st.error("Er is geen verwerkbaar blad gevonden in het Excel-bestand.")
            elif stages:
                st.session_state.stages = stages
                st.session_state.load_info = (
                    f"Excel-bestand gelezen — {len(stages)} fase(n) (bladen) "
                    f"gevonden: {', '.join(stages.keys())}"
                )
        else:
            delimiter = st.radio(
                "CSV-scheidingsteken", options=["Automatisch detecteren", ",", ";", "\\t"], horizontal=True,
            )
            sep_map = {"Automatisch detecteren": None, ",": ",", ";": ";", "\\t": "\t"}
            try:
                df = load_mapping_csv(uploaded_file, sep=sep_map[delimiter])
                stage_label = uploaded_file.name.rsplit(".", 1)[0] or "CSV"
                st.session_state.stages = {stage_label: df}
                st.session_state.load_info = f"CSV succesvol gelezen — {len(df)} rijen."
            except ValidationError as e:
                st.error(f"CSV-validatiefout:\n\n{e}")
            except Exception as e:
                st.error(f"CSV kon niet worden gelezen: {e}")

    if st.session_state.load_info:
        st.success(st.session_state.load_info)
    else:
        st.info("Upload een bestand om te beginnen, of download een sjabloon via de "
                "**:material/menu_book: Documentatie & hulp**-pagina.")

    if st.session_state.stages:
        st.divider()
        st.markdown("##### :material/sql: Gegenereerde views")
        with st.container(key="output_page"):
            use_create_or_alter = st.session_state.get("opt_create_or_alter", True)
            add_go = st.session_state.get("opt_add_go", True)

            stages = st.session_state.stages
            multi_stage = len(stages) > 1
            all_final_sqls = []

            if "output_stage" not in st.session_state or st.session_state.output_stage not in stages:
                st.session_state.output_stage = next(iter(stages))
            if "output_all_sqls" not in st.session_state:
                st.session_state.output_all_sqls = {}

            if multi_stage:
                with st.container(key="output_stage_nav"):
                    btn_cols = st.columns(len(stages))
                    for col, stage_name in zip(btn_cols, stages.keys()):
                        active = st.session_state.output_stage == stage_name
                        if col.button(
                            f"{_stage_icon(stage_name)}  {stage_name}",
                            key=f"output_stage_btn_{stage_name}",
                            type="primary" if active else "secondary",
                            width='stretch',
                        ):
                            st.session_state.output_stage = stage_name
                            st.rerun()
                st.divider()

                selected_stage = st.session_state.output_stage
                stage_sqls = render_stage(selected_stage, stages[selected_stage], use_create_or_alter, add_go)
                st.session_state.output_all_sqls[selected_stage] = stage_sqls

                # "Download alle fasen" moet ALLE fasen bevatten, ook fasen die de
                # gebruiker deze sessie nog niet heeft bezocht (sinds we nu, anders
                # dan bij tabs, maar 1 fase tegelijk renderen) -- daarom worden ze
                # hier stil (zonder UI) meegegenereerd als ze nog niet bezocht zijn.
                for stage_name, stage_df in stages.items():
                    if stage_name not in st.session_state.output_all_sqls:
                        results, _ = generate_all_views(stage_df, use_create_or_alter=use_create_or_alter, add_go=add_go)
                        st.session_state.output_all_sqls[stage_name] = [item["sql"] for item in results.values()]
                all_final_sqls = [
                    sql for name in stages for sql in st.session_state.output_all_sqls.get(name, [])
                ]
            else:
                stage_name, df = next(iter(stages.items()))
                all_final_sqls = render_stage(stage_name, df, use_create_or_alter, add_go)

            if multi_stage and all_final_sqls:
                st.divider()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    "Download ALLE views van ALLE fasen als één SQL-bestand",
                    data="\n\n".join(all_final_sqls).encode("utf-8"),
                    file_name=f"all_stages_{timestamp}.sql", mime="text/sql",
                    type="primary", icon=":material/download:",
                )



# ============================================================================
# PAGINA: Lineage
# ============================================================================
elif st.session_state.page == "Lineage":
    st.title(":material/hub: Lineage")
    st.caption(
        "Toont per **eindtabel** (een view die niet als bron voor een andere "
        "view dient) de volledige herkomst (lineage) over alle fasen heen -- "
        "bijv. Silver → GGM → Gold. Tussenliggende views (bijv. GGM) krijgen "
        "geen eigen tabblad, omdat hun herkomst al zichtbaar is binnen het "
        "diagram van de eindtabel die ze voedt."
    )
    st.markdown(
        """
        <div style="display:flex; gap:20px; align-items:center; margin:4px 0 18px 0;
                    font-size:0.85rem; color:#262624;">
            <span><span style="display:inline-block; width:11px; height:11px;
                border-radius:3px; background:#F6E2A8; border:1px solid #C9A227;
                margin-right:6px;"></span>Bronlaag (vroegste fase)</span>
            <span><span style="display:inline-block; width:11px; height:11px;
                border-radius:3px; background:#BFD7EF; border:1px solid #5B85B8;
                margin-right:6px;"></span>Tussenlaag</span>
            <span><span style="display:inline-block; width:11px; height:11px;
                border-radius:3px; background:#C9E4D3; border:1px solid #5A9B76;
                margin-right:6px;"></span>Doellaag (eindtabel)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not st.session_state.stages:
        st.info("Upload eerst een bestand op de **:material/home: Home**-pagina.")
        st.stop()

    lineage_index = build_lineage_index(st.session_state.stages)

    if not lineage_index:
        st.warning("Er zijn geen views gevonden om de lineage van te tonen.")
        st.stop()

    qnames = find_terminal_views(lineage_index)

    if "lineage_qname" not in st.session_state or st.session_state.lineage_qname not in qnames:
        st.session_state.lineage_qname = qnames[0]

    with st.container(key="lineage_stage_nav"):
        btn_cols = st.columns(len(qnames))
        for col, qname in zip(btn_cols, qnames):
            active = st.session_state.lineage_qname == qname
            if col.button(
                f":material/table_view:  {qname}",
                key=f"lineage_qname_btn_{qname}",
                type="primary" if active else "secondary",
                width='stretch',
            ):
                st.session_state.lineage_qname = qname
                st.rerun()
    st.divider()

    dot = build_lineage_dot(st.session_state.lineage_qname, lineage_index)
    st.graphviz_chart(dot)


# ============================================================================
# PAGINA: Instellingen
# ============================================================================
elif st.session_state.page == "Instellingen":
    st.title(":material/settings: Instellingen")

    with st.container(key="settings_card"):
        st.markdown("**SQL-generatie-opties**")
        st.toggle(
            "Gebruik CREATE OR ALTER VIEW",
            value=True, key="opt_create_or_alter",
            help="Indien uitgeschakeld wordt een gewone CREATE VIEW gegenereerd "
                 "(geeft een fout als de view al bestaat).",
        )
        st.toggle(
            "Voeg GO toe na elke view",
            value=True, key="opt_add_go",
            help="Batch-scheidingsteken om in SSMS / de Fabric SQL-editor in "
                 "één keer uit te voeren.",
        )
        st.caption(
            "Deze instellingen gelden voor alle fasen op de **:material/home: Home**-pagina "
            "en blijven bewaard zolang u de app niet herlaadt."
        )


# ============================================================================
# PAGINA: Documentatie & hulp
# ============================================================================
elif st.session_state.page == "Documentatie & hulp":
    st.title(":material/menu_book: Documentatie & hulp")
    st.caption("Download een sjabloon om te starten, of lees de veelgestelde vragen hieronder.")

    st.markdown("##### :material/download: Sjablonen downloaden")
    col_t1, col_t2 = st.columns(2)
    try:
        with open("template.csv", "rb") as f:
            csv_bytes = f.read()
        col_t1.download_button(
            "CSV-sjabloon", data=csv_bytes, file_name="csv2sql_template.csv",
            mime="text/csv", width='stretch', icon=":material/download:",
        )
        col_t1.caption(":material/info_i: Eén fase -- alle kolommen in één plat bestand.")
    except FileNotFoundError:
        col_t1.warning("template.csv ontbreekt")
    try:
        with open("template.xlsx", "rb") as f:
            xlsx_bytes = f.read()
        col_t2.download_button(
            "Excel-sjabloon", data=xlsx_bytes, file_name="csv2sql_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch', icon=":material/download:",
        )
        col_t2.caption(":material/info_i: Meerdere fasen als aparte bladen, bijv. Silver→GGM→Gold.")
    except FileNotFoundError:
        col_t2.warning("template.xlsx ontbreekt")

    st.divider()
    st.markdown("##### :material/quiz: Veelgestelde vragen")
    with st.expander("CSV/Excel-kolombeschrijvingen"):
        st.markdown(
            "**Kolomvolgorde:** eerst bron (`source_*`), dan doel (`target_*`).\n\n"
            "**Verplicht in elke rij:**\n"
            "- `source_schema`, `source_table`, `source_column`\n"
            "- `target_schema`, `target_table`\n\n"
            "**target_column + target_datatype:** Worden samen opgegeven (normale "
            "SELECT-kolom) **of** beide leeg gelaten — in dat geval is de rij "
            "*uitsluitend een filter* (voegt geen kolom toe aan SELECT, alleen "
            "`where_condition` wordt toegepast; in dat geval is `where_condition` "
            "verplicht).\n\n"
            "**Optionele kolommen:**\n"
            "- `source_system`: Voor cross-warehouse/lakehouse QUERIES (3-delige "
            "naamgeving, FROM/JOIN-kant). Vul hier de naam van het andere item in "
            "wanneer u verwijst naar een ander Warehouse/Lakehouse (bijv. als de "
            "GGM-laag in een ander Warehouse staat dan Gold). Leeg laten als het "
            "in hetzelfde warehouse staat.\n"
            "- `target_system`: Documenteert tot WELK warehouse/lakehouse deze view "
            "behoort. Indien ingevuld wordt een ECHTE 3-delige naamgeving gebruikt in "
            "`CREATE VIEW`: `[target_system].[target_schema].[view_name]` — nodig om "
            "warehouses met gelijknamige schema's te onderscheiden. Indien leeg blijft "
            "de eenvoudige 2-delige vorm `[target_schema].[view_name]` behouden. Moet "
            "**gelijk** zijn voor alle rijen binnen één `target_table`-groep (of "
            "allemaal leeg).\n"
            "- `source_datatype`: Indien leeg of gelijk aan target_datatype wordt "
            "geen CAST toegevoegd; indien verschillend wordt automatisch `CAST(...)` "
            "toegepast.\n"
            "- `transformation`: Aangepaste SQL-expressie. De placeholder `{src}` "
            "wordt vervangen door de bronkolomverwijzing (bijv. `UPPER({src})`, "
            "`CASE WHEN {src} < 18 THEN ... END`).\n"
            "- `where_condition`: Wordt toegevoegd aan de WHERE-voorwaarde van de "
            "view. `{src}` wordt vervangen door de eigen bronkolom van die rij. Als "
            "dit op meerdere rijen binnen dezelfde `target_table` wordt opgegeven, "
            "worden ze allemaal met **AND** gecombineerd.\n"
            "- `join_type` / `join_condition`: Als binnen één `target_table` "
            "meerdere brontabellen worden gebruikt, moeten deze op de **eerste "
            "rij** van die tabel worden opgegeven (`INNER` / `LEFT` / `RIGHT` / `FULL`)."
        )

    with st.expander(":material/link_2: Alias-/tabelprefixregel"):
        st.markdown(
            "Als een view **uit slechts één brontabel** wordt gevoed (geen JOIN), "
            "wordt in de SELECT-lijst **geen tabelprefix** voor kolomnamen gezet — "
            "alleen `[Kolom]`. Bij meerdere brontabellen (JOIN) wordt het formaat "
            "`[Alias].[Kolom]` gebruikt, omdat anders onduidelijk is uit welke "
            "tabel een kolom komt. Deze regel wordt automatisch toegepast en is "
            "niet instelbaar."
        )

    with st.expander(":material/extension: Wat zijn handmatige kolommen?"):
        st.markdown(
            "Op de **:material/home: Home**-pagina kunt u, onder elke view, één of meer "
            "**handmatig samengestelde kolommen** toevoegen die niet in de bron-/"
            "doeltabellen voorkomen — bijvoorbeeld een Business Key (om de "
            "uniciteit van records te controleren), een controlekolom, of iets "
            "anders. Wordt **niet** vanuit CSV/Excel toegevoegd.\n\n"
            "Per kolom voert u een naam en de onderdelen in, gescheiden door "
            "komma's, in de gewenste volgorde:\n"
            "- Voor **vaste tekst** gebruikt u aanhalingstekens: `\"OOST\"`\n"
            "- Voor **een kolom** typt u de doelkolomnaam exact, zonder "
            "aanhalingstekens: `PersoonID` — of gebruik het keuzemenu "
            "**'Kolom toevoegen'** om een bestaande kolom met één klik toe te "
            "voegen aan de onderdelen.\n\n"
            "Voorbeeldinvoer: `\"OOST\", PersoonID, Geboortedatum` →\n\n"
            "`CAST(CONCAT('OOST', ' | ', [PersoonID], ' | ', [Geboortedatum]) "
            "AS VARCHAR(255))`\n\n"
            "Elke kolom wordt **vooraan** in de SELECT-lijst toegevoegd, in de "
            "volgorde waarin u ze heeft aangemaakt; u kunt zoveel kolommen "
            "toevoegen als u wilt, en elk afzonderlijk weer verwijderen."
        )

    with st.expander(":material/hub: Wat toont de Lineage-pagina?"):
        st.markdown(
            "De **:material/hub: Lineage**-pagina toont voor elke gegenereerde "
            "view een diagram met de volledige herkomst over alle fasen heen "
            "(bijv. Silver → GGM → Gold). Dit wordt automatisch afgeleid uit de "
            "`source_table`-verwijzingen -- geen extra configuratie nodig."
        )
