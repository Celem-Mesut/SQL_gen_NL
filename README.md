# CSV/Excel → T-SQL View Üretici

Kaynak ve hedef (Microsoft Fabric Warehouse) tablo/kolon eşleştirmelerini içeren
bir **CSV** (tek aşama) ya da **çok sayfalı Excel** dosyasından (her sayfa
bağımsız bir aşama, örn. Silver→GGM, GGM→Gold) otomatik olarak
`CREATE OR ALTER VIEW` betikleri üreten, Streamlit tabanlı bir araç.
İstege bağlı olarak her view için bir veya daha fazla **manuel kolon**
(Business Key, kontrol kolonu, vb.) eklenebilir.

> **Dil notu:** Uygulamanın arayüzü (başlıklar, butonlar, hata mesajları) ve
> üretilen SQL'in başındaki yorum satırları **tamamen Hollandaca**'dır — bu,
> programın son kullanıcısı içindir. Bu Python dosyalarındaki **kod yorumları**
> (geliştirici notları) Türkçe kalmıştır, çünkü bunlar sizin için yazıldı.

## 🗺️ Sayfa yapısı

Uygulama **4 sayfaya** bölünmüştür, sol kenar çubuğundaki butonlarla gezilir
(aktif sayfa turuncu/vurgulu renkte, üzerine gelince kalınlaşır):

| Sayfa | İçerik |
|---|---|
| 🏠 **Home** | Dosya yükleme + tüm açıklama bölümleri |
| 📊 **Output** | Üretilen view'ler (çok-aşamalı Excel'de aşama başına bir sekme, örn. 🥈 Silver→GGM, 🥇 GGM→Gold) |
| ⚙️ **Instellingen** | `CREATE OR ALTER VIEW` / `GO` ayarları |
| 📄 **Sjablonen** | Şablon indirme + içeriklerinin önizlemesi |

Home'da yüklenen dosya `st.session_state` üzerinden saklanır — başka bir
sayfaya geçip geri döndüğünüzde veri kaybolmaz.

## Sayfa sembolleri (çok aşamalı Excel)

Excel'deki her sayfa, isminde geçen Medallion katmanına göre otomatik bir
sembol alır (hem Hollandaca hem İngilizce isimler tanınır):

| Sayfa adında geçen | Sembol |
|---|---|
| "gold" / "goud" | 🥇 |
| "silver" / "zilver" | 🥈 |
| "bronze" / "brons" | 🥉 |
| (tanınmayan) | 📂 |

Örnek: `Silver_to_GGM` → 🥈, `GGM_to_Gold` → 🥇.

## Kurulum ve çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

Proje klasöründe çalıştırırsanız `.streamlit/config.toml` içindeki Claude.ai'ye
yakın renk teması otomatik uygulanır (bkz. "Görsel tema" bölümü).

## Tek aşama (CSV) vs. çok aşama (Excel)

- **CSV** yüklerseniz, dosyanın tamamı tek bir aşama olarak işlenir.
- **Excel (.xlsx)** yüklerseniz, **her sayfa bağımsız bir aşama** olarak işlenir
  ve arayüzde **ayrı bir sekme (tab)** olarak gösterilir.
  Örnek: `Silver_to_GGM` sayfası Silver→GGM, `GGM_to_Gold` sayfası GGM→Gold
  view'lerini üretir. `template.xlsx`, GGM ve Gold katmanlarının **birbirinden
  bağımsız iki warehouse'da** (`GGM_Warehouse`, `Gold_Warehouse`) tutulduğu bu
  senaryoyu örnekler.

## CSV/Excel kolon formatı

Kolon sırası: önce kaynak (`source_*`), sonra hedef (`target_*`).

| Kolon | Zorunlu mu? | Açıklama |
|---|---|---|
| `source_system` | ❌ | **Okurken** kullanılacak çapraz warehouse referansı (3 parçalı isimlendirme, FROM/JOIN tarafında). Farklı bir Warehouse'a referans verirken o öğenin adı; aynı warehouse içindeyse boş bırakılabilir |
| `source_schema` | ✅ | Kaynak şema (örn. `Silver`, `GGM`) |
| `source_table` | ✅ | Kaynak tablo/view adı |
| `source_column` | ✅ | Kaynak kolon adı |
| `source_datatype` | ❌ | Boş veya `target_datatype` ile aynıysa `CAST` eklenmez; farklıysa otomatik `CAST(...)` uygulanır |
| `target_system` | ❌ | Bu view'in **hangi warehouse/lakehouse'a ait** olduğunu belgeler (bkz. aşağıdaki bölüm) |
| `target_schema` | ✅ | Hedef şema (örn. `GGM`, `Gold`) |
| `target_table` | ✅ | Hedef tablo adı (view adı otomatik `VW_` öneki alır) |
| `target_column` | ⚠️ | `target_datatype` ile **birlikte** verilir, ya da **birlikte** boş bırakılır (filtre-only satır) |
| `target_datatype` | ⚠️ | Hedef T-SQL veri tipi (örn. `NVARCHAR(200)`, `DECIMAL(18,2)`) |
| `transformation` | ❌ | Özel SQL ifadesi. `{src}` → kaynak kolon referansı (örn. `UPPER({src})`, `CASE WHEN {src} < 18 THEN ... END`) |
| `where_condition` | ❌ | View'in WHERE koşuluna eklenir. Aynı view içinde birden fazla satırda belirtilirse **AND** ile birleştirilir |
| `join_type` | ❌ | Birden fazla kaynak tablo varsa, o tabloya ait **ilk satırda** belirtilir (`INNER`/`LEFT`/`RIGHT`/`FULL`) |
| `join_condition` | ❌ | `join_type` ile birlikte, ON koşulu (serbest metin) |

### Filtre-only satırlar

`target_column` ve `target_datatype` ikisi de boş bırakılırsa, satır SELECT
listesine kolon eklemez; sadece `where_condition` üzerinden view'in WHERE
koşuluna katkıda bulunur (bu durumda `where_condition` zorunludur).

## 🔗 Alias / tablo öneki kuralı

Bir view **tek bir kaynak tablodan** besleniyorsa (JOIN yoksa), SELECT
listesinde kolon adlarının önüne tablo öneki **eklenmez**:

```sql
SELECT
    PersoonID,
    VolledigeNaam
FROM [Silver].[GGM_Persoon]
;
```

Birden fazla kaynak tablo (JOIN) varsa, hangi kolonun hangi tablodan geldiği
belirsiz olacağından `[Alias].[Kolon]` formatı kullanılır:

```sql
SELECT
    [VW_GGM_Inkomensvoorziening].[PersoonID] AS [PersoonID],
    [VW_GGM_Persoon].[VolledigeNaam] AS [PersoonNaam]
FROM [GGM_Warehouse].[GGM].[VW_GGM_Inkomensvoorziening] AS [VW_GGM_Inkomensvoorziening]
LEFT JOIN [GGM_Warehouse].[GGM].[VW_GGM_Persoon] AS [VW_GGM_Persoon]
    ON [VW_GGM_Inkomensvoorziening].[PersoonID] = [VW_GGM_Persoon].[PersoonID]
;
```

Bu kural otomatik uygulanır, CSV'den ayarlanamaz.

## 🏭 `target_system` — gerçek 3 parçalı isimlendirme

GGM ve Gold katmanları **birbirinden bağımsız warehouse'larda** tutuluyorsa
ve bu warehouse'larda **aynı isimde şemalar** varsa (örn. her ikisinde de
bir "Gold" şeması), 2 parçalı `[schema].[view]` isimlendirmesi yetersiz
kalır — hangi warehouse'a ait olduğu belirsizleşir. Bu yüzden `target_system`
doluysa, `CREATE OR ALTER VIEW` **gerçek 3 parçalı** bir isim kullanır:

```sql
CREATE OR ALTER VIEW [Gold_Warehouse].[Gold].[VW_FCT_PW_Inkomensvoorziening]
AS
...
```

`target_system` boşsa (tek warehouse senaryosu), eski sade 2 parçalı hâl
korunur:

```sql
CREATE OR ALTER VIEW [Gold].[VW_FCT_PW_Inkomensvoorziening]
AS
...
```

Bir `target_table` grubundaki **tüm satırlarda** `target_system` aynı olmalı
(veya hepsi boş). Arayüzdeki view başlığı ve indirilen `.sql` dosya adı da
**her zaman gerçek nitelikli adı** gösterir (örn.
`Gold_Warehouse.Gold.VW_FCT_PW_Inkomensvoorziening.sql`).

> **Not:** Microsoft'un resmi Fabric dokümantasyonu, `SELECT`/`INSERT`/`CTAS`
> için çapraz-warehouse 3 parçalı isimlendirmeyi açıkça doğruluyor, ancak bağlı
> olduğunuz warehouse'tan **farklı** bir warehouse'a doğrudan `CREATE VIEW`
> yapılıp yapılamayacağı dokümantasyonda açık değil. Bu özellik, kullanıcının
> kendi Fabric ortamındaki gözlemine göre eklendi — eğer Fabric'te syntax
> hatası verirse, haber verin.

## 🧩 Manuel kolonlar (Business Key ve daha fazlası)

**Output** sayfasında, her view'in altında **bir veya daha fazla** manuel
kolon ekleyebilirsiniz (Business Key, kontrol kolonu, veya başka bir amaçla):

1. "➕ Kolom toevoegen" ile yeni bir kolon satırı açın
2. **Kolomnaam** (kolon adı) ve **Onderdelen** (parçalar) girin — virgülle
   ayırarak, istediğiniz sırada:
   - **Sabit bir metin** için tırnak kullanın: `"OOST"`
   - **Bir kolon** için, hedef kolon adını tırnaksız aynen yazın: `PersoonID`
   - Ya da **"Kolom toevoegen" açılır menüsünden** mevcut bir kolonu seçip
     "➕ Toevoegen"e basarak, parçalara tek tıkla ekleyin (otomatik tamamlama)
3. İstediğiniz kadar kolon ekleyebilir, her birini "🗑️ Verwijder" ile ayrı
   ayrı silebilirsiniz

Örnek: `"OOST", PersoonID, Geboortedatum` → SELECT listesinin **en başına**:

```sql
CAST(CONCAT('OOST', ' | ', [PersoonID], ' | ', [Geboortedatum]) AS VARCHAR(255))
```

**Bu bir HASH DEĞİLDİR** — okunabilir/karşılaştırılabilir birleşik bir
anahtardır (composite key), `' | '` ile birleştirilip `VARCHAR(255)`'e
sınırlandırılır (255 karakterden uzunsa kesilir). Tüm manuel kolonlar,
oluşturma sırasıyla SELECT listesinin **en başına** eklenir.

## 🎨 Görsel tema

`.streamlit/config.toml`, Claude.ai'nin sıcak/krem renk paletine yakın bir
tema tanımlar (Anthropic marka renkleri: Crail `#C15F3C` vurgu, Pampas
`#F4F3EE` arka plan). Bu, **yaklaşık** bir eşleştirmedir — Anthropic'in
güncel resmi marka kılavuzunda kesin hex kodları değişmiş olabilir.

## Dosyalar

- `app.py` — Streamlit arayüzü (CSV + çok-sayfalı Excel + BK)
- `sql_generator.py` — CSV/Excel ayrıştırma + SQL üretim mantığı (bağımsız da kullanılabilir)
- `template.csv` — Tek aşamalı örnek
- `template.xlsx` — İki bağımsız warehouse'lu (GGM_Warehouse, Gold_Warehouse) iki aşamalı örnek
- `.streamlit/config.toml` — Renk teması
- `requirements.txt` — Bağımlılıklar

## Genişletme önerileri

- Aynı tabloyu bir view içinde iki farklı rolde kullanmak (self-join) şu an
  desteklenmiyor — gerekirse alias override için ek bir kolon eklenebilir
- BK seçimlerini bir oturum boyunca CSV/Excel'e "geri yazma" (export) imkânı
- `CREATE TABLE` veya `MERGE` modu da üretmek istersen, `sql_generator.py`
  içindeki `build_view_data` / `render_view_sql` çiftinin yanına aynı desende
  `build_table_data` / `render_create_table_sql` eklemek yeterli
