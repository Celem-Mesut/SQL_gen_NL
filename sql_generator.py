"""
csv2sql.sql_generator
----------------------
Kaynak -> hedef kolon mapping bilgisinden Microsoft Fabric Warehouse (T-SQL)
icin `CREATE OR ALTER VIEW` betikleri uretir.

Girdi iki sekilde olabilir:
    1) Tek bir CSV dosyasi -> tek "asama" (stage).
    2) Birden fazla sayfali bir Excel dosyasi -> her sayfa bagimsiz bir
       "asama" olarak islenir (orn. "Silver_to_GGM", "GGM_to_Gold"). GGM ve
       Gold katmanlari farkli warehouse/lakehouse'larda tutulduğunda,
       satirlardaki `source_system` (okurken hangi warehouse'tan) ve
       `target_system` (yazarken hangi warehouse'a) alanlari bu ayrimi
       belgeler.

CSV/sayfa kolon sirasi (once kaynak, sonra hedef):
    source_system, source_schema, source_table, source_column, source_datatype,
    target_system, target_schema, target_table, target_column, target_datatype,
    transformation, where_condition, join_type, join_condition

Her satir zorunlu olarak su alanlari icermelidir:
    source_schema, source_table, source_column, target_schema, target_table

target_column / target_datatype:
    Birlikte verilmelidir (normal bir SELECT kolonu uretir) VEYA her ikisi de
    bos birakilabilir -- bu durumda satir SADECE filtre amaclidir (asagidaki
    where_condition uygulanir, SELECT listesine kolon eklenmez). Filtre-only
    bir satirda where_condition zorunludur.

Opsiyonel kolonlar:
    source_system    -> capraz warehouse/lakehouse SORGUSU icin 3 parcali
                         isimlendirme (FROM/JOIN tarafinda). Bos birakilabilir.
    target_system    -> bu view'in HANGI warehouse/lakehouse'a ait oldugunu
                         belirtir. Doluysa, CREATE VIEW'in nitelik (qualifier)
                         konumunda GERCEK 3 parcali isimlendirme kullanilir:
                         [target_system].[target_schema].[view_name] --
                         ayni isimde semaya sahip birden fazla warehouse'u
                         birbirinden ayirt etmek icin gereklidir. Bossa, sade
                         2 parcali [target_schema].[view_name] kullanilir.
                         Bir target_table grubundaki TUM satirlarda AYNI
                         olmali (veya hepsi bos). Bkz. qualified_view_name().
    source_datatype  -> bos veya target_datatype ile ayniysa CAST uygulanmaz,
                         farkliysa otomatik CAST(...) eklenir.
    transformation   -> ozel SQL ifadesi. "{src}" yer tutucusu, kalifiye
                         kaynak kolon referansiyla degistirilir. CASE WHEN gibi
                         kosullu ifadeler de buraya yazilabilir.
    where_condition  -> View'in WHERE kosuluna eklenecek serbest metin SQL
                         ifadesi. "{src}" yer tutucusu o satirin kendi kaynak
                         kolon referansiyla degistirilir. Ayni target_table
                         grubunda birden fazla satirda belirtilirse AND ile
                         birlestirilir.
    join_type        -> Bir target_table grubunda birden fazla source_table
                         varsa, o tabloya ait ILK satirda belirtilmelidir.
    join_condition   -> join_type ile birlikte, o tabloya ait ILK satirda
                         belirtilmelidir (ON kosulu, serbest metin).

:material/link_2: Alias kurali (ONEMLI):
    Bir view SADECE TEK bir kaynak tablodan besleniyorsa (JOIN yoksa), SELECT
    listesinde kolon adlarinin onune tablo/alias ONEKI EKLENMEZ -- sadece
    "[Kolon]" yazilir, cunku tek tablo varken bu onek gereksiz gurultudur.
    Birden fazla kaynak tablo (JOIN) varsa, hangi kolonun hangi tablodan
    geldigi belirsiz olacagindan, "[Alias].[Kolon]" formati kullanilir.

:material/extension: Manuel kolonlar (Business Key VE daha fazlasi):
    Kaynak/hedef tablolarinda yer almayan, kullanici arayuzunden (Streamlit)
    manuel olarak her view icin ayri ayri eklenebilen, BIRLESIK (composite)
    anahtar kolonlari -- Business Key (kayitlarin essizligini kontrol etmek
    icin) en yaygin ornektir, ama herhangi bir amacla (kontrol kolonu, vb.)
    birden fazla kolon eklenebilir. CSV/Excel'den GELMEZ. HASH DEGILDIR --
    secilen parcalar ' | ' ile birlestirilip VARCHAR(255)'e CAST edilir
    (okunabilir/karsilastirilabilir kalir). Bkz. `parse_business_key_input`,
    `build_business_key_select_line` ve `render_view_sql(..., extra_columns=...)`.
"""

from collections import OrderedDict
import pandas as pd

ALWAYS_REQUIRED_COLUMNS = [
    "source_schema", "source_table", "source_column",
    "target_schema", "target_table",
]

CONDITIONAL_PAIR_COLUMNS = ["target_column", "target_datatype"]

OPTIONAL_COLUMNS = [
    "source_system", "source_datatype",
    "target_system",
    "transformation", "where_condition",
    "join_type", "join_condition",
]

REQUIRED_COLUMNS = ALWAYS_REQUIRED_COLUMNS  # geriye donuk uyumluluk icin

ALL_COLUMNS = [
    "source_system", "source_schema", "source_table", "source_column", "source_datatype",
    "target_system", "target_schema", "target_table", "target_column", "target_datatype",
    "transformation", "where_condition", "join_type", "join_condition",
]


class ValidationError(Exception):
    """CSV/Excel icerigi ile ilgili kullanici dostu hata mesajlari icin."""


# ----------------------------------------------------------------------------
# CSV / Excel okuma
# ----------------------------------------------------------------------------

def _clean_and_validate(df):
    """Bir DataFrame'i (CSV'den veya bir Excel sayfasindan gelen) temizler ve
    dogrular. Hem load_mapping_csv hem load_mapping_excel tarafindan kullanilir."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in ALWAYS_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(
            "Ontbrekende verplichte kolom(men): " + ", ".join(missing)
        )

    for col in OPTIONAL_COLUMNS + CONDITIONAL_PAIR_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df.fillna("")
    for col in ALL_COLUMNS:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": ""})

    # Excel sayfalarinda siklikla olusan tamamen bos satirlari at.
    df = df[~(df[ALL_COLUMNS].eq("").all(axis=1))].reset_index(drop=True)
    if df.empty:
        return df

    bad_rows = df[
        (df["source_schema"] == "") | (df["source_table"] == "") | (df["source_column"] == "")
        | (df["target_schema"] == "") | (df["target_table"] == "")
    ]
    if not bad_rows.empty:
        rij_woord = "rij" if len(bad_rows) == 1 else "rijen"
        raise ValidationError(
            f"Er zijn {len(bad_rows)} {rij_woord} gevonden met lege verplichte velden "
            f"(0-geïndexeerde rijnummers: {list(bad_rows.index)}). De velden "
            "source_schema, source_table, source_column, target_schema en "
            "target_table mogen in geen enkele rij leeg zijn."
        )

    half_filled = df[
        ((df["target_column"] == "") & (df["target_datatype"] != ""))
        | ((df["target_column"] != "") & (df["target_datatype"] == ""))
    ]
    if not half_filled.empty:
        raise ValidationError(
            "target_column en target_datatype moeten samen worden opgegeven, "
            "of samen leeg worden gelaten (voor een filter-only rij). "
            f"Foutieve rijen (0-geïndexeerd): {list(half_filled.index)}."
        )

    filter_only_missing_condition = df[(df["target_column"] == "") & (df["where_condition"] == "")]
    if not filter_only_missing_condition.empty:
        raise ValidationError(
            "Voor rijen waarin target_column en target_datatype leeg zijn "
            "gelaten (filter-only), is where_condition verplicht. Foutieve "
            f"rijen (0-geïndexeerd): {list(filter_only_missing_condition.index)}."
        )

    return df


def load_mapping_csv(filepath_or_buffer, sep=None):
    """Tek bir CSV dosyasini okur, dogrular ve temizler (tek asama)."""
    df = pd.read_csv(filepath_or_buffer, sep=sep, engine="python", dtype=str)
    return _clean_and_validate(df)


def load_mapping_excel(file_obj):
    """Birden fazla sayfali bir Excel dosyasini okur. Her sayfa bagimsiz bir
    asama (stage) olarak dogrulanir.

    Donus: (stages, errors)
        stages: OrderedDict[sheet_name] -> dogrulanmis DataFrame (basarili sayfalar)
        errors: OrderedDict[sheet_name] -> hata mesaji (basarisiz sayfalar, dahil edilmez)
    """
    xls = pd.ExcelFile(file_obj)
    stages = OrderedDict()
    errors = OrderedDict()
    for sheet_name in xls.sheet_names:
        try:
            raw_df = xls.parse(sheet_name, dtype=str)
            if raw_df.empty:
                continue
            df = _clean_and_validate(raw_df)
            if df.empty:
                continue
            stages[sheet_name] = df
        except ValidationError as e:
            errors[sheet_name] = str(e)
    return stages, errors


# ----------------------------------------------------------------------------
# SQL parcalarinin uretimi
# ----------------------------------------------------------------------------

def _qualified_source(row):
    parts = []
    if row["source_system"]:
        parts.append(f"[{row['source_system']}]")
    parts.append(f"[{row['source_schema']}]")
    parts.append(f"[{row['source_table']}]")
    return ".".join(parts)


def _view_name(target_table):
    if target_table.lower().startswith("vw_"):
        return target_table
    return f"VW_{target_table}"


def qualified_view_name(view_data, brackets=True):
    """View'in TAM nitelikli (qualified) adini olusturur:
        target_system varsa -> [target_system].[target_schema].[view_name]  (3 parcali)
        target_system yoksa  -> [target_schema].[view_name]                 (2 parcali)
    Hem render_view_sql (gercek SQL'de) hem app.py (baslik/dosya adi
    gostermek icin, koseli parantezsiz) tarafindan kullanilir -- tek bir
    yerden tanimlanip her ikisinde de TUTARLI kalmasi icin."""
    parts = []
    if view_data["target_system"]:
        parts.append(view_data["target_system"])
    parts.append(view_data["target_schema"])
    parts.append(view_data["view_name"])
    if brackets:
        return ".".join(f"[{p}]" for p in parts)
    return ".".join(parts)


def _source_ref(row, alias=None):
    """Bu satirin kaynak kolonuna SQL referansi. `alias` verilmemisse (None
    veya bos), sadece "[Kolon]" doner -- yani view'de TEK bir kaynak tablo
    varsa (JOIN yoksa) tablo/alias onekine ihtiyac yoktur."""
    if alias:
        return f"[{alias}].[{row['source_column']}]"
    return f"[{row['source_column']}]"


def _column_expression(row, alias=None):
    src_ref = _source_ref(row, alias)
    if row["transformation"]:
        return row["transformation"].replace("{src}", src_ref)

    src_type = row["source_datatype"].lower().replace(" ", "")
    tgt_type = row["target_datatype"].lower().replace(" ", "")
    if src_type and src_type != tgt_type:
        return f"CAST({src_ref} AS {row['target_datatype']})"
    return src_ref


def build_view_data(group_df, target_schema, target_table,
                     use_create_or_alter=True, add_go=True):
    """Bir (target_schema, target_table) grubuna ait tum satirlardan, henuz
    metne donusturulmemis yapisal bir view tanimi uretir. Bu yapi sonradan
    `render_view_sql` ile (istege bagli Business Key eklenerek) SQL metnine
    cevrilir. group_df CSV/sayfa sirasini korumalidir."""
    table_keys = OrderedDict()
    errors = []

    for _, row in group_df.iterrows():
        key = (row["source_system"], row["source_schema"], row["source_table"])
        if key not in table_keys:
            is_base = len(table_keys) == 0
            if not is_base and not row["join_condition"]:
                errors.append(
                    f"Voor tabel '{row['source_table']}' is geen join_condition "
                    f"opgegeven (target_table={target_table}). Wanneer een view "
                    f"meerdere brontabellen gebruikt, zijn join_type en "
                    f"join_condition verplicht op de eerste rij van die tabel."
                )
            table_keys[key] = {
                "alias": row["source_table"],
                "qualified": _qualified_source(row),
                "is_base": is_base,
                "join_type": (row["join_type"] or "INNER").upper(),
                "join_condition": row["join_condition"],
            }

    if errors:
        raise ValidationError("\n".join(errors))

    # JOIN varsa (birden fazla kaynak tablo) alias onekleri kullanilir;
    # tek tablo varsa kolon adlari sade kalir (bkz. modul docstring'i).
    has_join = len(table_keys) > 1

    # target_system: bu view'in ait oldugu warehouse/lakehouse. Bir grubun
    # TUM satirlarinda ayni olmali (veya hepsi bos).
    target_systems = {t for t in group_df["target_system"] if t}
    if len(target_systems) > 1:
        raise ValidationError(
            f"Voor '{target_table}' zijn meerdere verschillende target_system-"
            f"waarden gevonden: {sorted(target_systems)}. Alle rijen van een "
            "view moeten tot hetzelfde target_system behoren (of volledig leeg zijn)."
        )
    target_system = next(iter(target_systems), "")

    columns = []
    for _, row in group_df.iterrows():
        if not row["target_column"]:
            continue
        key = (row["source_system"], row["source_schema"], row["source_table"])
        alias = table_keys[key]["alias"] if has_join else None
        expr = _column_expression(row, alias)
        columns.append({"target_column": row["target_column"], "expr": expr})

    if not columns:
        raise ValidationError(
            f"Voor '{target_table}' zijn er geen kolommen om aan de SELECT-"
            "lijst toe te voegen (alle rijen zijn filter-only). Er is minstens "
            "één rij met een target_column/target_datatype-paar nodig."
        )

    from_lines = []
    for info in table_keys.values():
        if info["is_base"]:
            if has_join:
                from_lines.append(f"FROM {info['qualified']} AS [{info['alias']}]")
            else:
                from_lines.append(f"FROM {info['qualified']}")
        else:
            from_lines.append(
                f"{info['join_type']} JOIN {info['qualified']} AS [{info['alias']}]\n"
                f"    ON {info['join_condition']}"
            )

    where_conditions = []
    for _, row in group_df.iterrows():
        if not row["where_condition"]:
            continue
        key = (row["source_system"], row["source_schema"], row["source_table"])
        alias = table_keys[key]["alias"] if has_join else None
        cond = row["where_condition"].replace("{src}", _source_ref(row, alias))
        if cond not in where_conditions:
            where_conditions.append(cond)

    return {
        "target_schema": target_schema,
        "target_table": target_table,
        "target_system": target_system,
        "view_name": _view_name(target_table),
        "create_stmt": "CREATE OR ALTER VIEW" if use_create_or_alter else "CREATE VIEW",
        "add_go": add_go,
        "has_join": has_join,
        "columns": columns,
        "from_lines": from_lines,
        "where_conditions": where_conditions,
    }


def parse_business_key_input(raw_text, col_map):
    """Kullanicinin serbest metin olarak girdigi BK parcalarini ayristirir.

    raw_text: virgulle ayrilmis parcalar, kullanicinin istedigi sirada. Her parca:
        - Tek ('...') veya cift ("...") tirnak icindeyse SABIT BIR METIN (literal)
          olarak yorumlanir -> SQL string literaline cevrilir (orn. "GGM" -> 'GGM').
        - Aksi halde col_map icindeki bir target_column adina TAM olarak esit
          olmalidir -> o kolonun HAM ifadesi (CAST EKLENMEDEN) kullanilir. T-SQL'de
          CONCAT() tum parametreleri otomatik olarak string'e cevirir (implicit
          conversion), bu yuzden CAST(... AS NVARCHAR(4000)) eklemek gereksiz
          gurultudur -- bkz. build_business_key_select_line.
    Tirnak icindeki virguller boler olarak sayilmaz (orn. "a,b" tek bir parca olarak
    kalir).

    Donus: (parts, errors)
        parts: SQL'e hazir ifadelerin, kullanicinin yazdigi sirayla listesi
        errors: taninmayan/gecersiz parcalar icin kullanici dostu hata mesajlari
    """
    parts = []
    errors = []
    if not raw_text or not raw_text.strip():
        return parts, errors

    for raw_token in _split_bk_tokens(raw_text):
        token = raw_token.strip()
        if not token:
            continue
        if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0]:
            literal = token[1:-1].replace("'", "''")
            parts.append(f"'{literal}'")
        elif token in col_map:
            parts.append(col_map[token])
        else:
            errors.append(
                f"'{token}' is geen herkende kolomnaam en geen literal tussen "
                "aanhalingstekens. Gebruik enkele/dubbele aanhalingstekens voor "
                "vaste tekst (bijv. \"GGM\"), of typ voor een kolom de naam "
                "EXACT zoals een van de bestaande doelkolommen."
            )
    return parts, errors


def _split_bk_tokens(raw_text):
    """raw_text'i virgule gore boler, ancak tirnak icindeki virgulleri korur."""
    tokens = []
    current = []
    quote_char = None
    for ch in raw_text:
        if quote_char:
            current.append(ch)
            if ch == quote_char:
                quote_char = None
        elif ch in "\"'":
            quote_char = ch
            current.append(ch)
        elif ch == ",":
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def build_business_key_select_line(bk_name, parts):
    """parts: parse_business_key_input(...) ciktisi gibi, her biri zaten
    SQL'e hazir bir ifade olan (literal SQL string'i veya HAM kolon ifadesi)
    parcalarin sirali listesi. Hepsi ' | ' ile aralarina eklenerek
    birlestirilir ve VARCHAR(255)'e CAST edilir -- bu bir HASH DEGIL,
    okunabilir/karsilastirilabilir birlesik bir anahtardir (composite key)."""
    if not bk_name:
        raise ValidationError("De naam van de Business Key-kolom mag niet leeg zijn.")
    if not parts:
        raise ValidationError("Voor de Business Key moet minstens één onderdeel (kolom of literal) worden opgegeven.")

    if len(parts) == 1:
        concat_expr = parts[0]
    else:
        interleaved = []
        for i, part in enumerate(parts):
            if i > 0:
                interleaved.append("' | '")
            interleaved.append(part)
        concat_expr = "CONCAT(" + ", ".join(interleaved) + ")"

    bk_expr = f"CAST({concat_expr} AS VARCHAR(255))"
    return f"{bk_expr} AS [{bk_name}]"


def render_view_sql(view_data, extra_columns=None):
    """view_data (build_view_data ciktisi) icin nihai T-SQL metnini uretir.

    extra_columns: None veya bir LISTE, her biri {"name": str, "parts": [str, ...]}.
        Bu, kullanicinin arayuzden MANUEL olarak ekledigi kolonlardir (Business
        Key, kontrol kolonu, vs. -- herhangi bir amacla). "parts" zaten SQL'e
        hazir ifadelerdir (bkz. parse_business_key_input). Verilen SIRAYLA,
        SELECT listesinin EN BASINA eklenirler.
    """
    select_lines = []
    for extra in (extra_columns or []):
        if extra.get("parts"):
            line = build_business_key_select_line(extra["name"], extra["parts"])
            select_lines.append(f"    {line}")

    for col in view_data["columns"]:
        select_lines.append(f"    {col['expr']} AS [{col['target_column']}]")

    # target_system doluysa GERCEK 3 parcali isimlendirme kullanilir:
    # [target_system].[target_schema].[view_name]. Bu, ayni isimde semaya
    # sahip birden fazla warehouse'u birbirinden ayirt etmek icin GEREKLIDIR
    # (kullanicinin kendi Fabric ortaminda dogruladigi bir gereksinim).
    # target_system bossa, basit 2 parcali [target_schema].[view_name] kalir.
    sql = (
        f"{view_data['create_stmt']} {qualified_view_name(view_data)}\n"
        f"AS\n"
        f"SELECT\n"
        + ",\n".join(select_lines) + "\n"
        + "\n".join(view_data["from_lines"])
    )
    if view_data["where_conditions"]:
        sql += "\nWHERE\n    " + "\n    AND ".join(f"({c})" for c in view_data["where_conditions"])
    sql += "\n;"
    if view_data["add_go"]:
        sql += "\nGO"

    return sql


def generate_all_views(df, use_create_or_alter=True, add_go=True):
    """df icindeki tum satirlari (target_schema, target_table) bazinda gruplar
    ve her grup icin bir view tanimi + varsayilan (Business Key'siz) SQL uretir.

    Donus: (results, warnings)
        results: OrderedDict[(target_schema, target_table)] ->
                  {"view_name": str, "view_data": dict, "sql": str, "column_count": int}
        warnings: gruplandirma/validasyon hatalarinin listesi (varsa)
    """
    results = OrderedDict()
    warnings = []
    grouped = df.groupby(["target_schema", "target_table"], sort=False)
    for (target_schema, target_table), group_df in grouped:
        try:
            view_data = build_view_data(
                group_df, target_schema, target_table,
                use_create_or_alter=use_create_or_alter, add_go=add_go,
            )
            sql = render_view_sql(view_data)
            results[(target_schema, target_table)] = {
                "view_name": view_data["view_name"],
                "view_data": view_data,
                "sql": sql,
                "column_count": len(view_data["columns"]),
            }
        except ValidationError as e:
            warnings.append(str(e))
    return results, warnings


def combine_sql(results):
    """Tum view SQL'lerini (varsayilan, Business Key'siz halleriyle) tek bir
    betik halinde birlestirir."""
    return "\n\n".join(item["sql"] for item in results.values())
