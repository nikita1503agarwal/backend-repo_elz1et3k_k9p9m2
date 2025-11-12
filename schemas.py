"""
Database Schemas for Website Monitoring

Each Pydantic model represents a collection in your MongoDB database.
Collection name is the lowercase of the class name.

Collections:
- Category -> "category"
- Website -> "website"
- CheckResult -> "checkresult"
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List

class Category(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Nama kategori")
    color: Optional[str] = Field(None, description="Warna penanda kategori (hex)")

class Website(BaseModel):
    name: str = Field(..., min_length=2, max_length=150, description="Nama situs")
    url: HttpUrl = Field(..., description="URL situs yang dimonitor")
    category_id: Optional[str] = Field(None, description="ID kategori terkait")
    keywords: List[str] = Field(default_factory=list, description="Daftar kata kunci untuk dipantau")
    interval_seconds: int = Field(300, ge=30, le=86400, description="Interval pengecekan dalam detik")
    is_active: bool = Field(True, description="Apakah monitoring aktif")

class CheckResult(BaseModel):
    website_id: str = Field(..., description="ID website")
    status_code: Optional[int] = Field(None, description="HTTP status code")
    is_up: bool = Field(False, description="Apakah situs up")
    response_time_ms: Optional[int] = Field(None, description="Waktu respon dalam ms")
    keyword_matches: List[str] = Field(default_factory=list, description="Kata kunci yang ditemukan")
    error: Optional[str] = Field(None, description="Pesan error bila gagal")
