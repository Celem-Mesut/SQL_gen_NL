"""
conftest.py -- ortak test yardimcilari.

Testler proje kokunden calistirilir:
    pytest tests/ -v
"""
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

# Proje kokunu import yoluna ekle (tests/ klasorunden calisirken de bulunsun)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sql_generator import load_mapping_csv  # noqa: E402


def make_df(rows):
    """Satir sozluklerinden, uygulamanin kendi yukleme yolundan (load_mapping_csv)
    GECIRILMIS bir DataFrame uretir -- boylece testler, gercek kullanimla birebir
    ayni temizleme/normalizasyon adimlarini gorur (string'e cevirme, bos satir
    atma, eksik kolonlari '' ile doldurma)."""
    df = pd.DataFrame(rows)
    return load_mapping_csv(io.BytesIO(df.to_csv(index=False).encode("utf-8")))


@pytest.fixture
def simple_rows():
    """Tek tablo, iki kolonlu, en sade gecerli mapping."""
    return [
        dict(source_schema="Silver", source_table="X", source_column="ID",
             target_schema="Gold", target_table="Y", target_column="ID", target_datatype="INT"),
        dict(source_schema="Silver", source_table="X", source_column="NAAM",
             target_schema="Gold", target_table="Y", target_column="Naam", target_datatype="NVARCHAR(100)"),
    ]
