"""
ui_helpers.py
-------------
app.py'den bolunmus, YENIDEN KULLANILABILIR arayuz yapi taslari:
    - Onbellekli (st.cache_data) sarmalayicilar: cached_generate_all_views,
      cached_build_lineage_index, cached_preflight_validate
    - _stage_icon           -> faz adina gore Medallion sembolu
    - _append_suggestion    -> manuel-kolon secim yardimcisi (callback)
    - render_manual_columns_ui -> Business Key / manuel kolon formu
    - render_ai_assistant   -> NVIDIA AI syntax-kontrol + sohbet blogu
    - render_stage          -> bir fazin tum view'lerini (pre-flight raporu,
                               grup-hatasi duzeltme editoru, SQL kartlari,
                               indirme butonlari dahil) cizen ana fonksiyon

app.py sadece sayfa akislarini (Home/Lineage/Mapping-document/Instellingen/
Documentatie & hulp) ve genel kurulumu (CSS, session, sidebar) icerir.
st.session_state moduller arasinda paylasilir, bu yuzden bolunme davranisi
DEGISTIRMEZ -- yalnizca dosya organizasyonudur.
"""

import hashlib

import pandas as pd
import streamlit as st

from sql_generator import (
    generate_all_views,
    parse_business_key_input,
    preflight_validate,
    qualified_view_name,
    render_view_sql,
)
from lineage import build_lineage_index
from llm_client import DEFAULT_MODEL, ask_followup, check_sql_syntax


# ----------------------------------------------------------------------------
# Onbellekli (cached) sarmalayicilar -- generate_all_views ve
# build_lineage_index SAF (deterministik) fonksiyonlardir: ayni girdi her
# zaman ayni ciktiyi verir. st.cache_data, girdi DataFrame'leri
# degismedikce sonucu bellekten dondurur; boylece her sayfa gecisinde/
# rerun'da (Home, Lineage, Mapping-document ayni hesabi tekrar tekrar
# yapiyordu) SQL uretimi + lineage cikarimi BASTAN hesaplanmaz. Buyuk
# (50+ view'li) dosyalarda fark belirgin olur. Arayuzden yapilan
# duzeltmeler yeni bir DataFrame urettigi icin cache otomatik tazelenir.
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cached_generate_all_views(df, use_create_or_alter, add_go):
    return generate_all_views(df, use_create_or_alter=use_create_or_alter, add_go=add_go)


@st.cache_data(show_spinner=False)
def cached_build_lineage_index(stages):
    return build_lineage_index(stages)


@st.cache_data(show_spinner=False)
def cached_preflight_validate(df):
    return preflight_validate(df)


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
                # Belirsizligi onlemek icin: menude "Doelkolom <- bronexpressie"
                # birlikte gosterilir. SQL'e HER ZAMAN sagdaki BRONexpressie
                # yazilir -- SELECT'teki AS-takma-adi (doelkolomnaam) DEGIL.
                # (T-SQL, ayni SELECT icindeki bir alias'a referans verilmesine
                # izin vermez; arac bu yuzden alias'i hicbir zaman kullanmaz.)
                # Secim anahtari yine doelkolomnaam'dir, cunku UNION'li
                # view'lerde her dalin bronkolonu FARKLIDIR -- doelkolomnaam
                # tum dallarda gecerli tek ortak kimliktir ve her dal icin
                # kendi bronexpressiesine ayri ayri cevrilir.
                format_func=lambda opt: f"{opt}  ←  {col_map[opt]}" if opt else opt,
                help="Kies de doelkolom; in de SQL wordt automatisch de "
                     "onderliggende bronexpressie (rechts van de pijl) "
                     "ingevoegd -- nooit de AS-alias zelf.",
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
    def _friendly_api_error(e):
        """API hatasini, kullanicinin ne yapabilecegini soyleyen mesaja cevirir.
        'DEGRADED' = NVIDIA'nin barindirdigi model uc noktasi GECICI olarak
        hizmet disi (SQL'le/kodla ilgisi yok); llm_client zaten birkac kez
        otomatik denedi -- biraz bekleyip 'Opnieuw controleren' gerekir."""
        msg = str(e)
        if "DEGRADED" in msg:
            return (
                ":material/hourglass_top: Het NVIDIA-model is tijdelijk "
                "overbelast/onbeschikbaar (status 'DEGRADED' -- dit ligt aan "
                "NVIDIA's servers, niet aan uw SQL). Er is al automatisch een "
                "paar keer opnieuw geprobeerd. Wacht even en klik op "
                "**Opnieuw controleren**; houdt het aan, overweeg dan een "
                "ander model-ID in de secrets-configuratie."
            )
        return f":material/error: Fout bij aanroepen van NVIDIA API: {msg}"

    auto_check = st.session_state.get("opt_auto_ai_check", True)
    if "ai_check_cache" not in st.session_state:
        st.session_state.ai_check_cache = {}
    sql_hash = hashlib.md5(final_sql.encode("utf-8")).hexdigest()

    # OTOMATIK kontrol: SQL (hash'i) daha once kontrol edilmediyse, buton
    # beklemeden AI'ya gonder. Sonuc hash bazinda onbelleklenir -- ayni SQL
    # icin (rerun'lar, sayfa gecisleri) API TEKRAR CAGRILMAZ; SQL degisirse
    # (yeni upload, duzeltme, manuel kolon) hash degisir ve otomatik yeniden
    # kontrol edilir.
    if auto_check and sql_hash not in st.session_state.ai_check_cache:
        with st.spinner("Automatische AI-syntaxcontrole..."):
            try:
                st.session_state.ai_check_cache[sql_hash] = check_sql_syntax(api_key, model, final_sql)
            except Exception as e:
                st.session_state.ai_check_cache[sql_hash] = _friendly_api_error(e)

    if st.button("Opnieuw controleren", key=f"aicheck_btn_{view_key}", icon=":material/fact_check:"):
        with st.spinner("NVIDIA-model controleert de syntax..."):
            try:
                st.session_state.ai_check_cache[sql_hash] = check_sql_syntax(api_key, model, final_sql)
            except Exception as e:
                st.session_state.ai_check_cache[sql_hash] = _friendly_api_error(e)
    if sql_hash in st.session_state.ai_check_cache:
        st.info(st.session_state.ai_check_cache[sql_hash])

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
                answer = _friendly_api_error(e)
        st.session_state[hist_key].append({"role": "assistant", "content": answer})
        st.rerun()


def render_stage(stage_name, df, use_create_or_alter, add_go):
    """Bir asamaya (CSV veya bir Excel sayfasi) ait tum view'leri uretir,
    her biri icin manuel-kolon formuyla birlikte gosterir. Donus: o asamada
    uretilen tum nihai SQL metinlerinin listesi."""
    results, warnings = cached_generate_all_views(df, use_create_or_alter, add_go)

    # Pre-flight: kolom-bazli, satir-numarali kontrol raporu -- view uretimi
    # denenmeden once TUM sorunlari tek listede gosterir (grup-bazli uretim
    # hatalarinin tamamlayicisi, bkz. preflight_validate docstring'i).
    preflight_issues = cached_preflight_validate(df)
    if preflight_issues:
        with st.expander(
            f":material/rule: Controle van de invoer -- {len(preflight_issues)} "
            f"aandachtspunt(en) gevonden",
            expanded=True,
        ):
            st.caption(
                "**Excel-rij** verwijst naar het rijnummer in uw bronbestand "
                "(rij 1 = kolomkoppen). Herstel deze punten in uw bestand of "
                "via de herstel-editor hieronder (indien van toepassing)."
            )
            st.dataframe(
                pd.DataFrame(preflight_issues).rename(columns={
                    "excel_rij": "Excel-rij", "kolom": "Kolom", "probleem": "Probleem",
                }),
                width='stretch', hide_index=True,
            )

    if st.session_state.get("fix_result"):
        st.success(st.session_state.fix_result)
        st.session_state.fix_result = None

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
                    "Pas de cellen hieronder aan (bevestig elke celwijziging met "
                    "Enter), en klik daarna op Toepassen. Beweeg over een kolomkop "
                    "voor een invulvoorbeeld."
                )
                editor_key = f"fixeditor_{stage_name}_{w['target_schema']}_{w['target_table']}"
                rows_df = df.loc[w["row_indices"]].reset_index(drop=True)
                edited = st.data_editor(
                    rows_df,
                    key=editor_key,
                    num_rows="dynamic",
                    width='stretch',
                    column_config={
                        "transformation": st.column_config.TextColumn(
                            "transformation",
                            help="Bijv. UPPER({src}) of CASE WHEN {src} < 18 THEN "
                                 "'Minderjarig' ELSE 'Meerderjarig' END. Leeg = gewone kopie.",
                        ),
                        "where_condition": st.column_config.TextColumn(
                            "where_condition",
                            help="Bijv. {src} IS NOT NULL. Meerdere rijen worden met AND gecombineerd.",
                        ),
                        "join_type": st.column_config.TextColumn(
                            "join_type",
                            help="INNER / LEFT / RIGHT / FULL -- verplicht op de eerste "
                                 "rij van een nieuwe brontabel.",
                        ),
                        "join_condition": st.column_config.TextColumn(
                            "join_condition",
                            help="Bijv. [TabelA].[PersoonID] = [TabelB].[PersoonID].",
                        ),
                        "union_group": st.column_config.TextColumn(
                            "union_group",
                            help="Bijv. 1, 2, 3 -- andere waarde per UNION-tak binnen "
                                 "deze doeltabel.",
                        ),
                        "target_column": st.column_config.TextColumn(
                            "target_column",
                            help="Leeg + target_datatype ook leeg = filter-only rij.",
                        ),
                        "target_datatype": st.column_config.TextColumn(
                            "target_datatype",
                            help="Bijv. NVARCHAR(200), DECIMAL(18,2), DATE, INT.",
                        ),
                    },
                )

                if st.button(
                    "Toepassen & opnieuw genereren", key=f"fixapply_{editor_key}",
                    type="primary", icon=":material/check:",
                ):
                    try:
                        cleaned = edited.fillna("").astype(str)
                        remaining = df.drop(index=w["row_indices"])
                        new_df = pd.concat([remaining, cleaned], ignore_index=True)
                        st.session_state.stages[stage_name] = new_df
                        st.session_state.fix_result = (
                            f":material/check_circle: {len(cleaned)} rij(en) bijgewerkt "
                            f"voor {w['target_schema']}.{w['target_table']} -- opnieuw gegenereerd."
                        )
                        st.rerun()
                    except Exception as e:
                        st.exception(e)
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
