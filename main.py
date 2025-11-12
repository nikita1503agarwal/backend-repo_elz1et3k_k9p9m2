import os
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl
from bson import ObjectId
import requests

from database import db, create_document, get_documents
from schemas import Category as CategorySchema, Website as WebsiteSchema, CheckResult as CheckResultSchema

app = FastAPI(title="Website Monitoring API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utilities

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")


def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    doc["_id"] = str(doc.get("_id"))
    # Convert datetime to isoformat for JSON safety
    for key, val in list(doc.items()):
        if hasattr(val, "isoformat"):
            doc[key] = val.isoformat()
    return doc


# Pydantic I/O Models

class CategoryIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    color: Optional[str] = Field(None)

class CategoryOut(CategoryIn):
    id: str

class WebsiteIn(BaseModel):
    name: str
    url: HttpUrl
    category_id: Optional[str] = None
    keywords: List[str] = []
    interval_seconds: int = Field(300, ge=30, le=86400)
    is_active: bool = True

class WebsiteOut(WebsiteIn):
    id: str

class CheckResultOut(BaseModel):
    id: str
    website_id: str
    status_code: Optional[int] = None
    is_up: bool
    response_time_ms: Optional[int] = None
    keyword_matches: List[str] = []
    error: Optional[str] = None
    created_at: Optional[str] = None


@app.get("/")
def read_root():
    return {"message": "Website Monitoring API running"}


@app.get("/api/categories", response_model=List[CategoryOut])
def list_categories():
    items = list(db["category"].find().sort("name", 1))
    return [CategoryOut(id=str(i["_id"]), name=i.get("name"), color=i.get("color")) for i in items]


@app.post("/api/categories", response_model=CategoryOut)
def create_category(payload: CategoryIn):
    cat = CategorySchema(**payload.model_dump())
    new_id = create_document("category", cat)
    return CategoryOut(id=new_id, **payload.model_dump())


@app.get("/api/websites", response_model=List[WebsiteOut])
def list_websites():
    items = list(db["website"].find().sort("name", 1))
    out = []
    for i in items:
        out.append(
            WebsiteOut(
                id=str(i["_id"]),
                name=i.get("name"),
                url=i.get("url"),
                category_id=(str(i.get("category_id")) if isinstance(i.get("category_id"), ObjectId) else i.get("category_id")),
                keywords=i.get("keywords", []),
                interval_seconds=i.get("interval_seconds", 300),
                is_active=i.get("is_active", True),
            )
        )
    return out


@app.post("/api/websites", response_model=WebsiteOut)
def create_website(payload: WebsiteIn):
    data = payload.model_dump()
    # Store category_id as string
    if data.get("category_id"):
        try:
            # keep as string to avoid confusion
            pass
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid category_id")
    doc = WebsiteSchema(**data)
    new_id = create_document("website", doc)
    return WebsiteOut(id=new_id, **payload.model_dump())


@app.get("/api/websites/{website_id}", response_model=WebsiteOut)
def get_website(website_id: str):
    item = db["website"].find_one({"_id": oid(website_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Website not found")
    return WebsiteOut(
        id=str(item["_id"]),
        name=item.get("name"),
        url=item.get("url"),
        category_id=(str(item.get("category_id")) if isinstance(item.get("category_id"), ObjectId) else item.get("category_id")),
        keywords=item.get("keywords", []),
        interval_seconds=item.get("interval_seconds", 300),
        is_active=item.get("is_active", True),
    )


class CheckResponse(BaseModel):
    result: CheckResultOut


@app.post("/api/check/{website_id}", response_model=CheckResponse)
def run_check(website_id: str):
    item = db["website"].find_one({"_id": oid(website_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Website not found")

    url = item.get("url")
    keywords: List[str] = item.get("keywords", [])

    status_code = None
    is_up = False
    response_time_ms = None
    error = None
    matches: List[str] = []

    try:
        start = time.perf_counter()
        resp = requests.get(url, timeout=15)
        duration = (time.perf_counter() - start) * 1000
        response_time_ms = int(duration)
        status_code = resp.status_code
        is_up = 200 <= resp.status_code < 400
        content = resp.text.lower() if resp and resp.text else ""
        for kw in keywords:
            if kw and kw.lower() in content:
                matches.append(kw)
    except Exception as e:
        error = str(e)[:500]
        is_up = False

    check_doc = CheckResultSchema(
        website_id=website_id,
        status_code=status_code,
        is_up=is_up,
        response_time_ms=response_time_ms,
        keyword_matches=matches,
        error=error,
    )
    new_id = create_document("checkresult", check_doc)
    out = CheckResultOut(
        id=new_id,
        website_id=website_id,
        status_code=status_code,
        is_up=is_up,
        response_time_ms=response_time_ms,
        keyword_matches=matches,
        error=error,
        created_at=None,
    )
    return CheckResponse(result=out)


@app.get("/api/checks/latest", response_model=List[CheckResultOut])
def latest_checks(limit: int = 20, website_id: Optional[str] = None):
    filt = {"website_id": website_id} if website_id else {}
    # Sort by created_at descending; our helper sets timestamps
    items = list(db["checkresult"].find(filt).sort("created_at", -1).limit(limit))
    out: List[CheckResultOut] = []
    for i in items:
        out.append(
            CheckResultOut(
                id=str(i["_id"]),
                website_id=i.get("website_id"),
                status_code=i.get("status_code"),
                is_up=i.get("is_up", False),
                response_time_ms=i.get("response_time_ms"),
                keyword_matches=i.get("keyword_matches", []),
                error=i.get("error"),
                created_at=(i.get("created_at").isoformat() if i.get("created_at") else None),
            )
        )
    return out


@app.get("/api/summary")
def summary():
    total_sites = db["website"].count_documents({})
    total_categories = db["category"].count_documents({})
    recent = list(db["checkresult"].find().sort("created_at", -1).limit(200))
    up = sum(1 for r in recent if r.get("is_up"))
    down = len(recent) - up
    avg_rt = None
    rts = [r.get("response_time_ms") for r in recent if r.get("response_time_ms")]
    if rts:
        avg_rt = int(sum(rts) / len(rts))
    return {
        "total_sites": total_sites,
        "total_categories": total_categories,
        "recent_checks": len(recent),
        "up": up,
        "down": down,
        "avg_response_time_ms": avg_rt,
    }


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
