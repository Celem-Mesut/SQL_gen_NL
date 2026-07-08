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

import pandas as pd
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
from doc_export import build_stage_documentation
from lineage import build_lineage_dot, build_lineage_index, build_lineage_mermaid, find_terminal_views
from llm_client import DEFAULT_MODEL, ask_followup, check_sql_syntax

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
if "nvidia_api_key" not in st.session_state:
    # st.secrets: yerelde .streamlit/secrets.toml'dan (gitignored), Streamlit
    # Community Cloud'da ise repo'ya hic dokunmayan "Settings -> Secrets"
    # panelinden okunur. secrets.toml hic yoksa hata vermeden bos doner.
    try:
        st.session_state.nvidia_api_key = st.secrets.get("NVIDIA_API_KEY", "")
    except Exception:
        st.session_state.nvidia_api_key = ""
if "nvidia_model" not in st.session_state:
    try:
        st.session_state.nvidia_model = st.secrets.get("NVIDIA_MODEL", "") or DEFAULT_MODEL
    except Exception:
        st.session_state.nvidia_model = DEFAULT_MODEL

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
       Monokromatik derinlik sistemi -- ACIK'tan KOYU'ya, arkadan one:
         #ffffff (white)          -> sayfa arka plani (0. katman)
         #c1e2e2 (frozen-water)   -> sidebar / ikincil yuzey (1. katman)
         #82c4c5 (pearl-aqua)     -> cerceveler (2. katman)
         #44a6a8 (tropical-teal)  -> birincil eylem/aktif durum (3. katman)
         #05888a (dark-cyan)      -> basliklar, en on plandaki vurgu (4. katman)
       Metin govdesi #1C2B2B (notr, teal-tonlu koyu) -- okunabilirlik icin
       saf dark-cyan yerine, ama baslikar dark-cyan ile "en on planda".
       ------------------------------------------------------------------- */
    h1, h2, h3, [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        letter-spacing: -0.01em;
        font-weight: 600 !important;
        color: #05888a !important;
    }
    code, pre, [data-testid="stCodeBlock"] *, .stCodeBlock * {
        font-family: 'JetBrains Mono', 'Courier New', monospace !important;
    }

    [data-testid="stExpander"] {
        border: 1px solid #82c4c5 !important;
        border-radius: 10px !important;
        background: #FFFFFF;
        box-shadow: 0 1px 3px rgba(5, 136, 138, 0.08);
        overflow: hidden;
    }
    [data-testid="stExpander"] summary {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 500;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #82c4c5;
        border-radius: 8px;
        padding: 14px 18px;
    }
    [data-testid="stMetricLabel"] { font-family: 'Inter', sans-serif; opacity: 0.7; }
    [data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif; color: #05888a; }

    /* Fase-/tab-schakelaars (Home-output + Lineage): actief = tropical-teal
       (primaryColor), inactief = pearl-aqua omkaderd. */
    [class*="_stage_nav"] button {
        font-size: 1.05rem !important;
        font-family: 'Space Grotesk', sans-serif !important;
        font-weight: 600 !important;
        padding: 0.9rem 1.2rem !important;
        border-radius: 10px !important;
    }
    [class*="_stage_nav"] button[kind="secondary"] {
        border-color: #82c4c5 !important;
        color: #05888a !important;
    }

    /* Sidebar: frozen-water (1. katman) -- lichter dan de content-
       achtergrond is niet mogelijk (wit is al de lichtste), dus dit is
       de eerste stap "naar voren" in de gelaagdheid. Tekst blijft donker
       (goede leesbaarheid op een lichte achtergrond). */
    [data-testid="stSidebar"] {
        background: #c1e2e2;
        border-right: 1px solid #82c4c5;
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
    [data-testid="stSidebar"] button[kind="secondary"] {
        border-color: #82c4c5 !important;
    }

    /* Instellingen-kaart: instellingen niet los in een lege pagina laten
       zweven, maar in een afgebakend kader. */
    .st-key-settings_card, .st-key-ai_settings_card {
        border: 1px solid #82c4c5;
        border-radius: 12px;
        padding: 24px 28px;
        background: #FFFFFF;
        max-width: 640px;
        margin-bottom: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

NAV_PAGES = [
    ("Home", ":material/home:"),
    ("Lineage", ":material/hub:"),
    ("Mapping-document", ":material/description:"),
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
            extra_columns.append({"name": name, "parts": parts, "raw_text": raw_parts})

    return extra_columns


# ----------------------------------------------------------------------------
# Output: bir asamayi (CSV/Excel sayfasi) ureten ve gosteren fonksiyon
# ----------------------------------------------------------------------------

def render_ai_assistant(view_key, final_sql):
    """Bir view karti icin, opsiyonel NVIDIA AI-destegini gosterir: (1) tek
    tikla syntax kontrolu, (2) o SQL uzerine serbest metinli iyilestirme/
    "fine-tuning" sorulari icin kucuk bir sohbet gecmisi. API key girilmemisse
    sadece Instellingen'e yonlendiren kisa bir not gosterir -- ozellik hic
    zorunlu degildir. LLM'in cevaplari SADECE TAVSIYEDIR: asil uretilen SQL'i
    otomatik olarak DEGISTIRMEZ (bkz. llm_client.py docstring'i)."""
    api_key = st.session_state.get("nvidia_api_key", "")
    model = st.session_state.get("nvidia_model", DEFAULT_MODEL)

    st.divider()
    st.caption(":material/smart_toy: AI-assistent (NVIDIA) -- adviserend, past de SQL hierboven niet automatisch aan")

    if not api_key:
        st.caption(
            "Voer een NVIDIA API-key in op de **:material/settings: Instellingen**-"
            "pagina om syntaxcontrole en verfijningsvragen te gebruiken."
        )
        return

    check_key = f"aicheck_{view_key}"
    if st.button("Syntax controleren", key=f"aicheck_btn_{view_key}", icon=":material/fact_check:"):
        with st.spinner("NVIDIA-model controleert de syntax..."):
            try:
                st.session_state[check_key] = check_sql_syntax(api_key, model, final_sql)
            except Exception as e:
                st.session_state[check_key] = f":material/error: Fout bij aanroepen van NVIDIA API: {e}"
    if check_key in st.session_state:
        st.info(st.session_state[check_key])

    hist_key = f"aichat_{view_key}"
    if hist_key not in st.session_state:
        st.session_state[hist_key] = []
    for turn in st.session_state[hist_key]:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])

    with st.form(key=f"aiform_{view_key}", clear_on_submit=True, border=False):
        col_q, col_send = st.columns([5, 1])
        question = col_q.text_input(
            "Vervolgvraag / verfijningsverzoek", key=f"aiinput_{view_key}",
            label_visibility="collapsed",
            placeholder="Bijv. 'Voeg een filter toe op actieve records'",
        )
        submitted = col_send.form_submit_button(":material/send:", width='stretch')
    if submitted and question.strip():
        st.session_state[hist_key].append({"role": "user", "content": question})
        with st.spinner("NVIDIA-model denkt na..."):
            try:
                answer = ask_followup(api_key, model, final_sql, st.session_state[hist_key][:-1], question)
            except Exception as e:
                answer = f":material/error: Fout bij aanroepen van NVIDIA API: {e}"
        st.session_state[hist_key].append({"role": "assistant", "content": answer})
        st.rerun()


def render_stage(stage_name, df, use_create_or_alter, add_go):
    """Bir asamaya (CSV veya bir Excel sayfasi) ait tum view'leri uretir,
    her biri icin manuel-kolon formuyla birlikte gosterir. Donus: o asamada
    uretilen tum nihai SQL metinlerinin listesi."""
    results, warnings = generate_all_views(df, use_create_or_alter=use_create_or_alter, add_go=add_go)

    if warnings:
        st.warning(
            f":material/error: Er zijn {len(warnings)} groep(en) overgeslagen "
            "omdat ze fouten bevatten. Herstel ze direct hieronder -- geen "
            "nieuwe upload nodig."
        )
        for w in warnings:
            with st.expander(
                f":material/build: Herstellen: {w['target_schema']}.{w['target_table']} "
                f"({len(w['row_indices'])} rij(en))",
                expanded=True,
            ):
                st.markdown(f":material/info_i: **Fout:** {w['message']}")
                st.caption(
                    "Pas de rijen hieronder direct aan (voeg zo nodig een rij toe "
                    "of verwijder er een), en klik daarna op Toepassen. Beweeg over "
                    "een kolomkop voor een invulvoorbeeld."
                )
                editor_key = f"fixeditor_{stage_name}_{w['target_schema']}_{w['target_table']}"
                rows_df = df.loc[w["row_indices"]].reset_index(drop=True)
                with st.form(key=f"fixform_{editor_key}"):
                    edited = st.data_editor(
                        rows_df,
                        key=editor_key,
                        num_rows="dynamic",
                        width='stretch',
                        column_config={
                            "transformation": st.column_config.TextColumn(
                                "transformation",
                                help="Aangepaste SQL-expressie. {src} = bronkolom. "
                                     "Bijv. UPPER({src}) of CASE WHEN {src} < 18 THEN "
                                     "'Minderjarig' ELSE 'Meerderjarig' END. Leeg = gewone kopie.",
                            ),
                            "where_condition": st.column_config.TextColumn(
                                "where_condition",
                                help="Filter voor de WHERE-clausule. {src} = bronkolom van "
                                     "DEZE rij. Bijv. {src} IS NOT NULL. Meerdere rijen "
                                     "worden met AND gecombineerd.",
                            ),
                            "join_type": st.column_config.TextColumn(
                                "join_type",
                                help="INNER / LEFT / RIGHT / FULL -- verplicht op de "
                                     "EERSTE rij van een NIEUWE brontabel (niet nodig voor "
                                     "de allereerste/basistabel).",
                            ),
                            "join_condition": st.column_config.TextColumn(
                                "join_condition",
                                help="De ON-voorwaarde, vrije tekst. Bijv. "
                                     "[TabelA].[PersoonID] = [TabelB].[PersoonID]. Verplicht "
                                     "samen met join_type.",
                            ),
                            "union_group": st.column_config.TextColumn(
                                "union_group",
                                help="Bijv. 1, 2, 3 -- een ANDERE waarde per UNION-tak "
                                     "binnen deze doeltabel. Leeg = geen union. Nummers "
                                     "hoeven alleen binnen deze doeltabel uniek te zijn.",
                            ),
                            "target_column": st.column_config.TextColumn(
                                "target_column",
                                help="Naam van de doelkolom. Leeg + target_datatype ook "
                                     "leeg = deze rij is uitsluitend een filter (geen "
                                     "SELECT-kolom).",
                            ),
                            "target_datatype": st.column_config.TextColumn(
                                "target_datatype",
                                help="Bijv. NVARCHAR(200), DECIMAL(18,2), DATE, INT.",
                            ),
                        },
                    )
                    submitted = st.form_submit_button(
                        "Toepassen & opnieuw genereren",
                        type="primary", icon=":material/check:",
                    )
                if submitted:
                    cleaned = edited.fillna("").astype(str)
                    remaining = df.drop(index=w["row_indices"])
                    new_df = pd.concat([remaining, cleaned], ignore_index=True)
                    st.session_state.stages[stage_name] = new_df
                    st.rerun()
        st.divider()

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

            render_ai_assistant(view_key, final_sql)
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
                    font-size:0.85rem; color:#1C2B2B;">
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

    with st.expander(":material/data_object: Mermaid-code weergeven (voor wiki's)"):
        st.caption(
            "Deze code geeft PRECIES hetzelfde diagram (dezelfde knopen, "
            "pijlen en kleuren) weer als Mermaid-syntax -- rechtstreeks "
            "bruikbaar in een ```mermaid codeblok op een Azure DevOps Wiki-"
            "pagina (of GitHub/GitLab). Gebruik het kopieerpictogram rechts-"
            "boven in het codeblok."
        )
        mermaid_code = build_lineage_mermaid(st.session_state.lineage_qname, lineage_index)
        st.code(mermaid_code, language="text")


# ============================================================================
# PAGINA: Mapping-document
# ============================================================================
elif st.session_state.page == "Mapping-document":
    st.title(":material/description: Mapping-document")

    if not st.session_state.stages:
        st.info("Upload eerst een bestand op de **:material/home: Home**-pagina.")
        st.stop()

    stages = st.session_state.stages
    use_create_or_alter = st.session_state.get("opt_create_or_alter", True)
    add_go = st.session_state.get("opt_add_go", True)
    lineage_index = build_lineage_index(stages)

    st.caption(
        "Eén Markdown-document PER FASE, met kolomtoewijzing, filters/joins/"
        "union en lineage (Mermaid) -- geschikt om te kopiëren of downloaden "
        "en in een wiki (bijv. Azure DevOps Wiki) te plakken. De gegenereerde "
        "SQL zelf staat hier bewust niet in (die staat al op de "
        "**:material/home: Home**-pagina)."
    )

    if "mapping_doc_stage" not in st.session_state or st.session_state.mapping_doc_stage not in stages:
        st.session_state.mapping_doc_stage = next(iter(stages))

    multi_stage = len(stages) > 1
    if multi_stage:
        with st.container(key="mapping_doc_stage_nav"):
            btn_cols = st.columns(len(stages))
            for col, stage_name in zip(btn_cols, stages.keys()):
                active = st.session_state.mapping_doc_stage == stage_name
                if col.button(
                    f"{_stage_icon(stage_name)}  {stage_name}",
                    key=f"mapping_doc_stage_btn_{stage_name}",
                    type="primary" if active else "secondary",
                    width='stretch',
                ):
                    st.session_state.mapping_doc_stage = stage_name
                    st.rerun()
        st.divider()

    selected_stage = st.session_state.mapping_doc_stage
    stage_df = stages[selected_stage]
    results, _warnings = generate_all_views(stage_df, use_create_or_alter=use_create_or_alter, add_go=add_go)

    view_entries = []
    for (target_schema, target_table), item in results.items():
        view_key = f"{selected_stage}::{target_schema}::{target_table}"
        group_df = stage_df[
            (stage_df["target_schema"] == target_schema) & (stage_df["target_table"] == target_table)
        ]
        view_entries.append({
            "stage_name": selected_stage, "view_data": item["view_data"],
            "group_df": group_df, "view_key": view_key,
        })

    st.markdown("##### :material/edit_note: Business toelichtingen (optioneel)")
    st.caption(
        "Vult u hier niets in, dan blijft die sectie in het document leeg -- "
        "u kunt het document dan zonder toelichting kopiëren en zelf verder "
        "aanvullen op uw wiki-pagina."
    )
    purposes = {}
    for entry in view_entries:
        vk = entry["view_key"]
        with st.expander(f":material/edit: {qualified_view_name(entry['view_data'])}"):
            purposes[vk] = st.text_area(
                "Business toelichting", key=f"purpose_{vk}", label_visibility="collapsed",
                placeholder="Bijv. 'Deze view voedt het BI-rapport voor de Participatiewet-uitkeringen.'",
                height=80,
            )

    st.divider()
    doc = build_stage_documentation(selected_stage, view_entries, lineage_index, purposes)

    st.markdown(f"##### :material/description: Document — {selected_stage}")
    st.code(doc, language="markdown")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        f"Download {selected_stage} als Markdown (.md)", data=doc.encode("utf-8"),
        file_name=f"mapping_documentatie_{selected_stage}_{timestamp}.md", mime="text/markdown",
        icon=":material/download:", type="primary",
    )


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

    st.markdown("")
    with st.container(key="ai_settings_card"):
        st.markdown("**:material/smart_toy: NVIDIA AI-assistent**")
        st.caption(
            "Voor AI-syntaxcontrole en verfijningsvragen bij gegenereerde views "
            "(zie de **:material/home: Home**-pagina, onder elke view)."
        )
        model = st.session_state.get("nvidia_model", DEFAULT_MODEL)
        api_key_set = bool(st.session_state.get("nvidia_api_key", ""))
        st.caption(f":material/memory: Model: `{model}`")
        st.caption(
            (":material/check_circle: API-key is geconfigureerd door de beheerder."
             if api_key_set else
             ":material/cancel: Geen API-key geconfigureerd -- de AI-assistent is uitgeschakeld.")
        )
        st.caption(
            "De API-key en het model worden centraal beheerd (via secrets.toml/"
            "Streamlit Secrets) en zijn hier alleen ter informatie -- niet "
            "wijzigbaar door gebruikers."
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
    with st.expander(":material/list_alt: Kolomvolgorde & verplichte velden"):
        st.markdown(
            "**Kolomvolgorde:** eerst bron (`source_*`), dan doel (`target_*`).\n\n"
            "**Verplicht in elke rij:**\n"
            "- `source_schema`, `source_table`, `source_column`\n"
            "- `target_schema`, `target_table`\n\n"
            "**target_column + target_datatype:** worden **samen** opgegeven "
            "(normale SELECT-kolom) **of** beide leeg gelaten -- in dat geval is "
            "de rij *uitsluitend een filter* (voegt geen kolom toe aan SELECT, "
            "alleen `where_condition` wordt toegepast; in dat geval is "
            "`where_condition` op die rij verplicht).\n\n"
            "**source_datatype:** indien leeg of gelijk aan `target_datatype` "
            "wordt geen `CAST` toegevoegd; indien verschillend wordt automatisch "
            "`CAST(...)` toegepast."
        )

    with st.expander(":material/dns: source_system & target_system"):
        st.markdown(
            "**`source_system`** (optioneel): voor cross-warehouse/lakehouse "
            "LEESVERWIJZINGEN (3-delige naamgeving, aan de FROM/JOIN-kant). Vul "
            "hier de naam van het andere item in wanneer u verwijst naar een "
            "ANDER Warehouse/Lakehouse dan waar deze view zelf in komt (bijv. "
            "de GGM-laag staat in een ander Warehouse dan Gold). Leeg laten als "
            "bron en doel in hetzelfde warehouse staan.\n\n"
            "**`target_system`** (optioneel): documenteert ENKEL tot welk "
            "warehouse/lakehouse deze view zelf behoort -- **puur informatief**. "
            "Het verandert de `CREATE VIEW` NIET: die gebruikt altijd de "
            "eenvoudige 2-delige vorm `[target_schema].[view_name]`, ongeacht "
            "wat hier staat. Indien ingevuld wordt het alleen als een "
            "commentaarregel bovenaan het gegenereerde script gezet (\"tegen "
            "welke warehouse-verbinding moet ik dit script uitvoeren?\"), en in "
            "de bestandsnaam bij downloaden. Moet **gelijk** zijn voor alle "
            "rijen binnen één `target_table`-groep (of allemaal leeg)."
        )

    with st.expander(":material/functions: transformation"):
        st.markdown(
            "Een aangepaste SQL-expressie voor deze kolom, in plaats van een "
            "kale 1-op-1 kopie. De placeholder **`{src}`** wordt vervangen door "
            "de verwijzing naar de eigen bronkolom van die rij (met het juiste "
            "alias-voorvoegsel indien er meerdere brontabellen zijn).\n\n"
            "**Voorbeelden:**\n"
            "- `UPPER({src})` → tekst in hoofdletters\n"
            "- `CASE WHEN {src} < 18 THEN 'Minderjarig' ELSE 'Meerderjarig' END` "
            "→ berekende categorie\n"
            "- `CAST({src} AS DATE)` → expliciete conversie (naast de "
            "automatische CAST op basis van `source_datatype`/`target_datatype`)\n\n"
            "Leeg laten = gewone kopie van de bronkolom (met automatische CAST "
            "indien nodig)."
        )

    with st.expander(":material/filter_alt: where_condition"):
        st.markdown(
            "Wordt toegevoegd aan de `WHERE`-voorwaarde van de view. De "
            "placeholder **`{src}`** wordt vervangen door de bronkolom van "
            "DEZELFDE rij.\n\n"
            "**Voorbeeld:** rij met `source_column=DAT_EIND`, "
            "`where_condition={src} IS NULL` → `WHERE ([DAT_EIND] IS NULL)`.\n\n"
            "**Meerdere filters:** als dit op meerdere rijen binnen dezelfde "
            "`target_table` (of dezelfde union-tak, zie `union_group`) wordt "
            "opgegeven, worden ze allemaal met **AND** gecombineerd.\n\n"
            "**Let op bij UNION:** een filter geldt alleen voor de tak "
            "(`union_group`) waarin die rij staat -- wordt niet automatisch "
            "gekopieerd naar andere takken."
        )

    with st.expander(":material/call_merge: join_type & join_condition"):
        st.markdown(
            "Nodig wanneer binnen één `target_table` **meerdere brontabellen** "
            "worden gecombineerd door middel van een JOIN (kolommen naast "
            "elkaar zetten -- voor rijen onder elkaar combineren, zie "
            "`union_group`).\n\n"
            "**Regel:** op de **eerste rij** waarop een NIEUWE brontabel "
            "verschijnt (binnen die `target_table`, of binnen die union-tak), "
            "moeten beide worden ingevuld:\n"
            "- `join_type`: `INNER` / `LEFT` / `RIGHT` / `FULL`\n"
            "- `join_condition`: de `ON`-voorwaarde, vrije tekst (bijv. "
            "`[TabelA].[PersoonID] = [TabelB].[PersoonID]`)\n\n"
            "De EERSTE brontabel die voor die `target_table` verschijnt heeft "
            "GEEN `join_condition` nodig -- dat is de basistabel waar de andere "
            "tabellen op aansluiten."
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

    with st.expander(":material/call_split: Hoe vul ik union_group correct in?"):
        st.markdown(
            "**Veelgemaakte fout:** dezelfde `union_group`-waarde geven aan "
            "ALLE brontabellen van een doeltabel (bijv. alles `1`). Dit "
            "vertelt het systeem dat die tabellen met JOIN gecombineerd "
            "moeten worden, niet met UNION -- en JOIN vereist "
            "`join_type`/`join_condition`, wat de foutmelding veroorzaakt.\n\n"
            "**Juiste aanpak:** elke brontabel die een EIGEN UNION-tak moet "
            "worden, krijgt een ANDERE `union_group`-waarde binnen dezelfde "
            "doeltabel (bijv. `1`, `2`, `3`). Deze nummering hoeft alleen "
            "binnen één doeltabel uniek te zijn -- u mag `1`, `2`, `3` "
            "gerust hergebruiken voor een volgende doeltabel.\n\n"
            "**Let op bij where_condition:** elke UNION-tak past ALLEEN zijn "
            "eigen `where_condition`-rijen toe -- een filter wordt niet "
            "automatisch naar andere takken gekopieerd. Wilt u dezelfde "
            "filter op alle takken, vul die dan expliciet in bij elke tak."
        )
