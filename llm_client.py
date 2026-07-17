"""
llm_client.py
-------------
NVIDIA NIM (build.nvidia.com) ile OpenAI-uyumlu chat completions API'sine
baglanan ince bir istemci katmani. Iki islev icin kullanilir:
    1. check_sql_syntax  -> uretilen T-SQL/Fabric Warehouse script'inin
                             syntax'ini kontrol eder.
    2. ask_followup       -> kullanicinin o script uzerinde yapmak istedigi
                             iyilestirme/"fine-tuning" sorularina cevap verir.

ONEMLI TASARIM KARARI: Bu modul SADECE TAVSIYE verir. LLM'in verdigi cevap
veya onerdigi alternatif SQL, projenin CSV/Excel'den DETERMINISTIK olarak
uretilen "resmi" SQL'ini OTOMATIK OLARAK DEGISTIRMEZ -- kullanici, onerilen
degisikligi isterse kendi CSV/Excel'ine manuel olarak yansitir. Bu, aracin
"ayni girdi -> ayni SQL" garantisini (ki bircok gecmis debug oturumunda
onemi ortaya cikti) korur.

API anahtari hicbir zaman diske yazilmaz veya loglanmaz -- sadece
st.session_state uzerinden, tarayici oturumu suresince bellekte tutulur.

Kurulum:
    pip install openai
    (build.nvidia.com uzerinden ucretsiz bir hesapla "nvapi-..." ile
    baslayan bir API key alinir.)
"""

import time

from openai import OpenAI

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# GUVENLIK NOTU: API key ARTIK bu dosyada hardcoded DEGIL -- bir GitHub
# reposuna baglanmis Streamlit ortaminda bu, key'in git gecmisine sizmasi
# anlamina gelir. Key/model artik ".streamlit/secrets.toml" (yerelde,
# .gitignore'da) veya Streamlit Community Cloud'un "Settings -> Secrets"
# panelinden okunuyor -- bkz. app.py'deki st.secrets kullanimi ve
# ".streamlit/secrets.toml.example" sablonu.

# Varsayilan model -- build.nvidia.com/models katalogundaki guncel model
# kimligiyle degistirilebilir (katalog zaman icinde degisebilir, bu yuzden

# Instellingen sayfasinda serbest metin olarak duzenlenebilir tutuldu).
DEFAULT_MODEL = "qwen/qwen2.5-coder-32b-instruct"

SYNTAX_CHECK_SYSTEM_PROMPT = (
    "Je bent een T-SQL / Microsoft Fabric Warehouse (Polaris engine) "
    "syntaxcontroleur. Je krijgt een gegenereerd CREATE OR ALTER VIEW-"
    "script. Controleer ALLEEN de syntax en Fabric Warehouse-"
    "compatibiliteit (bijv. functies/datatypes die Polaris niet "
    "ondersteunt). Geef GEEN mening over business-logica of "
    "kolomkeuzes. Antwoord kort, in het Nederlands: een puntsgewijze "
    "lijst van gevonden problemen, of een korte bevestiging dat de "
    "syntax correct is als er niets is gevonden."
)

FOLLOWUP_SYSTEM_PROMPT = (
    "Je bent een T-SQL / Microsoft Fabric Warehouse expert-assistent. "
    "De gebruiker heeft een automatisch gegenereerd CREATE OR ALTER "
    "VIEW-script en wil dit verder verfijnen op basis van vragen of "
    "aanpassingsverzoeken. Antwoord kort en concreet in het Nederlands. "
    "Geef aangepaste SQL terug in een codeblok wanneer relevant. "
    "Belangrijk: jouw voorstel wordt NIET automatisch teruggeschreven "
    "naar de bron-CSV/Excel of het echte gegenereerde script -- het is "
    "uitsluitend een suggestie die de gebruiker zelf kan overnemen."
)


def _client(api_key):
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)


# Gecici (transient) hata isaretleri: bunlar gorulurse cagri, kisa bir
# beklemeyle otomatik olarak yeniden denenir. "DEGRADED": build.nvidia.com'un
# barindirdigi bir model uc noktasinin GECICI olarak asiri yuklu/hizmet disi
# isaretlenmesi -- genellikle saniyeler/dakikalar icinde kendini toparlar.
_TRANSIENT_MARKERS = ("DEGRADED", "429", "500", "502", "503", "504", "timed out", "timeout")
_MAX_RETRIES = 2
_BACKOFF_SECONDS = 2.0


def _chat_with_retry(client, **kwargs):
    """client.chat.completions.create'i, GECICI hatalarda (bkz.
    _TRANSIENT_MARKERS) artan beklemeyle en fazla _MAX_RETRIES kez yeniden
    dener. Kalici hatalar (401 auth, gecersiz istek vb.) ANINDA yukselir."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            if attempt < _MAX_RETRIES and any(m in str(e) for m in _TRANSIENT_MARKERS):
                time.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise


def check_sql_syntax(api_key, model, sql):
    """Verstuurt de SQL naar het NVIDIA NIM-model voor een syntaxcontrole.
    Retourneert de tekstuele beoordeling (str). Kan een uitzondering
    opgooien (netwerk-/authenticatiefout) -- de aanroeper vangt deze af."""
    client = _client(api_key)
    response = _chat_with_retry(
        client,
        model=model,
        messages=[
            {"role": "system", "content": SYNTAX_CHECK_SYSTEM_PROMPT},
            {"role": "user", "content": f"```sql\n{sql}\n```"},
        ],
        temperature=0.1,
        max_tokens=800,
    )
    return response.choices[0].message.content


def ask_followup(api_key, model, sql, history, question):
    """Vervolgvraag/verfijningsverzoek over een specifieke SQL-view.
    'history' is een lijst van {'role': ..., 'content': ...} dicts met
    eerdere beurten in dit gesprek (strikt afwisselend user/assistant).

    BELANGRIJK: de SQL-context wordt NIET als aparte, losstaande user-
    boodschap vóór de geschiedenis geplaatst -- dat zou twee opeenvolgende
    user-beurten opleveren (system -> user[sql] -> user[history[0]]), wat
    NVIDIA's model afwijst met "conversation roles must alternate
    user/assistant/...". In plaats daarvan wordt de SQL alleen in de EERSTE
    vraag van het gesprek ingebed; latere vervolgvragen bouwen voort op de
    geschiedenis, die al strikt alterneert."""
    client = _client(api_key)
    messages = [{"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT}]
    messages.extend(history)
    if history:
        messages.append({"role": "user", "content": question})
    else:
        messages.append({
            "role": "user",
            "content": f"Hier is de huidige SQL:\n```sql\n{sql}\n```\n\n{question}",
        })
    response = _chat_with_retry(
        client, model=model, messages=messages, temperature=0.3, max_tokens=1200,
    )
    return response.choices[0].message.content
