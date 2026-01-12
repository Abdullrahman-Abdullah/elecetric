from fastapi import FastAPI, Body, Query, HTTPException, Path
from database import products_collection, categories_collection, transactions_collection
from models import Product, Category, Transaction # الموديل الذي ناقشناه سابقاً
from typing import Optional
from bson import ObjectId
from pymongo import ReturnDocument
from datetime import datetime, timedelta
import time
from email.utils import formatdate
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import base64
import uuid



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



# أضف إلى بداية الملف
from pydantic import BaseModel
from typing import Optional
import hashlib
import secrets

# موديلات جديدة للبائعين
class Vendor(BaseModel):
    id: Optional[str] = None
    name: str
    email: str
    phone: Optional[str] = None
    username: str
    password_hash: str
    is_active: bool = True
    created_at: Optional[datetime] = None

class VendorLogin(BaseModel):
    username: str
    password: str

class VendorCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    username: str
    password: str

# collection للبائعين
from database import vendors_collection

# دوال مساعدة
def hash_password(password: str) -> str:
    """تشفير كلمة المرور"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    """التحقق من كلمة المرور"""
    return hash_password(password) == password_hash

# إنشاء جدول البائعين إذا لم يكن موجوداً
async def init_vendors_collection():
    try:
        # إنشاء فهرس فريد لاسم المستخدم
        await vendors_collection.create_index("username", unique=True)
        await vendors_collection.create_index("email", unique=True)
        print("✅ Vendors collection initialized")
    except Exception as e:
        print(f"⚠️  Vendors collection init warning: {e}")

# استدعاء الدالة عند بدء التشغيل
@app.on_event("startup")
async def startup_db_client():
    await init_vendors_collection()

# APIs جديدة للبائعين
@app.post("/api/vendors/register", response_description="تسجيل بائع جديد")
async def register_vendor(vendor: VendorCreate):
    # التحقق من عدم تكرار اسم المستخدم أو البريد
    existing = await vendors_collection.find_one({
        "$or": [
            {"username": vendor.username},
            {"email": vendor.email}
        ]
    })
    
    if existing:
        raise HTTPException(status_code=400, detail="اسم المستخدم أو البريد الإلكتروني مستخدم بالفعل")
    
    # إنشاء كائن البائع
    vendor_data = {
        "name": vendor.name,
        "email": vendor.email,
        "phone": vendor.phone,
        "username": vendor.username,
        "password_hash": hash_password(vendor.password),
        "is_active": True,
        "created_at": datetime.utcnow()
    }
    
    # إضافة إلى قاعدة البيانات
    result = await vendors_collection.insert_one(vendor_data)
    
    # إرجاع البيانات بدون كلمة المرور
    vendor_data["_id"] = str(result.inserted_id)
    vendor_data["id"] = vendor_data["_id"]
    del vendor_data["password_hash"]
    
    return vendor_data

@app.post("/api/vendors/login", response_description="تسجيل دخول البائع")
async def login_vendor(credentials: VendorLogin):
    # البحث عن البائع
    vendor = await vendors_collection.find_one({"username": credentials.username})
    
    if not vendor:
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
    
    # التحقق من كلمة المرور
    if not verify_password(credentials.password, vendor.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
    
    if not vendor.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب غير مفعل")
    
    # إنشاء رمز الدخول (Token)
    token = secrets.token_hex(32)
    
    # تخزين الرمز مؤقتاً (في الواقع يجب استخدام JWT)
    vendor_token = {
        "vendor_id": str(vendor["_id"]),
        "token": token,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(hours=24)
    }
    
    # إرجاع بيانات الدخول
    return {
        "token": token,
        "vendor": {
            "id": str(vendor["_id"]),
            "name": vendor["name"],
            "email": vendor["email"],
            "username": vendor["username"],
            "phone": vendor.get("phone")
        }
    }

@app.get("/api/vendors", response_description="جلب قائمة البائعين")
async def get_vendors(active_only: bool = True, skip: int = 0, limit: int = 100):
    query = {}
    if active_only:
        query["is_active"] = True
    
    cursor = vendors_collection.find(query).skip(skip).limit(limit)
    vendors_list = []
    
    async for vendor in cursor:
        vendor_data = {
            "id": str(vendor["_id"]),
            "name": vendor["name"],
            "email": vendor["email"],
            "phone": vendor.get("phone"),
            "username": vendor["username"],
            "is_active": vendor.get("is_active", True),
            "created_at": vendor.get("created_at")
        }
        vendors_list.append(vendor_data)
    
    return vendors_list

@app.get("/api/vendors/{vendor_id}/qr", response_description="إنشاء QR Code للبائع")
async def generate_vendor_qr(vendor_id: str):
    vendor = await vendors_collection.find_one({"_id": ObjectId(vendor_id)})
    
    if not vendor:
        raise HTTPException(status_code=404, detail="البائع غير موجود")
    
    # بيانات QR Code
    qr_data = {
        "vendor_id": str(vendor["_id"]),
        "username": vendor["username"],
        "name": vendor["name"],
        "type": "vendor_login",
        "timestamp": datetime.utcnow().isoformat(),
        "url": f"/api/vendors/login/qr/{str(vendor['_id'])}"
    }
    
    return qr_data

@app.post("/api/vendors/login/qr/{vendor_id}", response_description="تسجيل دخول عبر QR Code")
async def login_with_qr(vendor_id: str, qr_token: str = Body(...)):
    # هنا يمكنك التحقق من صحة QR Token
    # في هذا المثال سنقبل أي طلب للتبسيط
    
    vendor = await vendors_collection.find_one({"_id": ObjectId(vendor_id)})
    
    if not vendor:
        raise HTTPException(status_code=404, detail="البائع غير موجود")
    
    if not vendor.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب غير مفعل")
    
    # إنشاء رمز الدخول
    token = secrets.token_hex(32)
    
    return {
        "token": token,
        "vendor": {
            "id": str(vendor["_id"]),
            "name": vendor["name"],
            "email": vendor["email"],
            "username": vendor["username"],
            "phone": vendor.get("phone")
        },
        "message": "تم تسجيل الدخول بنجاح عبر QR Code"
    }



# Serve frontend static files from the `static` directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve product images from ./images
images_dir = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(images_dir, exist_ok=True)
app.mount("/images", StaticFiles(directory=images_dir), name="images")


@app.get("/", include_in_schema=False)
async def root():
    """Return the frontend index.html when visiting the root path."""
    # Prefer a project-root `index.html` if the user attached a custom UI there.
    repo_root_index = os.path.join(os.path.dirname(__file__), "index.html")
    static_index = os.path.join(static_dir, "index.html") if static_dir else None

    if os.path.isfile(repo_root_index):
        return FileResponse(repo_root_index)

    if static_index and os.path.isfile(static_index):
        return FileResponse(static_index)

    return {"detail": "Frontend not found"}

@app.get("/seller", include_in_schema=False)
async def root():
    """Return the frontend index.html when visiting the root path."""
    # Prefer a project-root `index.html` if the user attached a custom UI there.
    repo_root_index = os.path.join(os.path.dirname(__file__), "seller.html")
    static_index = os.path.join(static_dir, "seller.html") if static_dir else None

    if os.path.isfile(repo_root_index):
        return FileResponse(repo_root_index)

    if static_index and os.path.isfile(static_index):
        return FileResponse(static_index)

    return {"detail": "Frontend not found"}



# في main.py أضف هذه الوظيفة
from fastapi.responses import Response
import base64

# إنشاء صورة افتراضية
DEFAULT_IMAGE_SVG = """<svg width="60" height="60" viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="60" height="60" fill="#E5E5E5"/>
<path d="M30 20C33.3137 20 36 17.3137 36 14C36 10.6863 33.3137 8 30 8C26.6863 8 24 10.6863 24 14C24 17.3137 26.6863 20 30 20Z" fill="#B2B2B2"/>
<path d="M38 34L22 34C20 34 18 32 18 30L18 26C18 24 20 22 22 22L38 22C40 22 42 24 42 26L42 30C42 32 40 34 38 34Z" fill="#B2B2B2"/>
</svg>"""

@app.get("/images/default-image.png")
async def get_default_image():
    """إرجاع صورة افتراضية للمنتجات بدون صور"""
    svg_bytes = DEFAULT_IMAGE_SVG.encode('utf-8')
    return Response(content=svg_bytes, media_type="image/svg+xml")

@app.get("/images/{filename}")
async def get_product_image(filename: str):
    """إرجاع صورة المنتج أو الصورة الافتراضية"""
    image_path = os.path.join(images_dir, filename)
    
    if not os.path.exists(image_path):
        # إرجاع صورة افتراضية إذا لم توجد الصورة
        svg_bytes = DEFAULT_IMAGE_SVG.encode('utf-8')
        return Response(content=svg_bytes, media_type="image/svg+xml")
    
    # تحديد نوع الملف
    if filename.endswith('.png'):
        media_type = "image/png"
    elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
        media_type = "image/jpeg"
    elif filename.endswith('.gif'):
        media_type = "image/gif"
    else:
        media_type = "image/png"
    
    return FileResponse(image_path, media_type=media_type)

# إصلاح دالة create_product_flexible
@app.post("/products", response_description="إضافة منتج جديد (مرن)")
async def create_product_flexible(payload: dict = Body(...)):
    """Fallback endpoint that accepts flexible product JSON from the legacy frontend."""
    # If payload contains base64 image data under `imageData`, save it to disk and replace with `imagePath`.
    if isinstance(payload, dict) and payload.get('imageData'):
        img_data = payload.pop('imageData')
        try:
            # data URL may be like: data:image/jpeg;base64,/9j/...
            if isinstance(img_data, str) and img_data.startswith('data:'):
                _meta, b64 = img_data.split(',', 1)
                meta = _meta.split(';')[0]  # e.g. data:image/jpeg
                mime = meta.split(':')[1] if ':' in meta else 'image/jpeg'
            else:
                b64 = img_data
                mime = 'image/jpeg'

            binary = base64.b64decode(b64)
            ext = 'jpg'
            if 'png' in mime:
                ext = 'png'
            elif 'gif' in mime:
                ext = 'gif'
            filename = f"{uuid.uuid4().hex}.{ext}"
            path = os.path.join(images_dir, filename)
            with open(path, 'wb') as f:
                f.write(binary)
            # public path served at /images/<filename>
            payload['imagePath'] = f"/images/{filename}"
        except Exception as e:
            print(f"Warning: Invalid image data: {e}")
            # إذا كان هناك خطأ في الصورة، استخدم الصورة الافتراضية
            payload['imagePath'] = "/images/default-image.png"
    else:
        # إذا لم توجد صورة، استخدم الصورة الافتراضية
        payload['imagePath'] = "/images/default-image.png"

    doc = jsonable_encoder(payload)
    new_product = await products_collection.insert_one(doc)
    created = await products_collection.find_one({"_id": new_product.inserted_id})
    if created and created.get("_id"):
        created["_id"] = str(created["_id"])
    return created

# إصلاح دالة update_product
@app.patch("/product/{product_id}", response_description="تحديث منتج جزئياً")
async def update_product(product_id: str = Path(...), updates: dict = Body(...)):
    oid = to_object_id(product_id)
    # Prevent updating _id
    updates.pop("_id", None)
    # If client sent base64 `imageData`, save file and set `imagePath` instead
    if isinstance(updates, dict) and updates.get('imageData'):
        img_data = updates.pop('imageData')
        try:
            if isinstance(img_data, str) and img_data.startswith('data:'):
                _meta, b64 = img_data.split(',', 1)
                meta = _meta.split(';')[0]
                mime = meta.split(':')[1] if ':' in meta else 'image/jpeg'
            else:
                b64 = img_data
                mime = 'image/jpeg'

            binary = base64.b64decode(b64)
            ext = 'jpg'
            if 'png' in mime:
                ext = 'png'
            elif 'gif' in mime:
                ext = 'gif'
            filename = f"{uuid.uuid4().hex}.{ext}"
            path = os.path.join(images_dir, filename)
            with open(path, 'wb') as f:
                f.write(binary)
            updates['imagePath'] = f"/images/{filename}"
        except Exception as e:
            print(f"Warning: Invalid image data: {e}")
            # إذا كان هناك خطأ في الصورة، استخدم الصورة الافتراضية
            updates['imagePath'] = "/images/default-image.png"
    
    result = await products_collection.find_one_and_update(
        {"_id": oid},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    result["_id"] = str(result["_id"])
    return result




@app.get("/api/products/last-modified")
async def get_last_modified():
    """إرجاع آخر وقت تم فيه تحديث أي منتج"""
    try:
        # استخدام aggregation للبحث عن آخر منتج تم تحديثه
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"updatedAt": {"$exists": True}},
                        {"createdAt": {"$exists": True}}
                    ]
                }
            },
            {
                "$project": {
                    "last_modified": {
                        "$cond": {
                            "if": {"$gt": ["$updatedAt", "$createdAt"]},
                            "then": "$updatedAt",
                            "else": "$createdAt"
                        }
                    }
                }
            },
            {"$sort": {"last_modified": -1}},
            {"$limit": 1}
        ]
        
        async for result in products_collection.aggregate(pipeline):
            if result.get("last_modified"):
                if isinstance(result["last_modified"], datetime):
                    timestamp = int(result["last_modified"].timestamp() * 1000)
                else:
                    timestamp = int(time.time() * 1000)
                
                product_count = await products_collection.count_documents({})
                
                return {
                    "lastModified": timestamp,
                    "productCount": product_count,
                    "success": True
                }
        
        # إذا لم توجد منتجات
        return {
            "lastModified": 0,
            "productCount": 0,
            "success": True
        }
        
    except Exception as e:
        print(f"Error in last-modified: {e}")
        return {
            "lastModified": int(time.time() * 1000),
            "productCount": 0,
            "success": False,
            "error": str(e)
        }

@app.get("/api/products/quick-check")
async def quick_check():
    """فحص سريع للتغييرات بدون جلب كل البيانات"""
    try:
        # 1. عدد المنتجات
        product_count = await products_collection.count_documents({})
        
        # 2. آخر منتج تم إضافته أو تعديله
        latest_product = await products_collection.find_one(
            {},
            sort=[("$natural", -1)]  # أحدث وثيقة في قاعدة البيانات
        )
        
        last_timestamp = 0
        if latest_product:
            # حاول الحصول على وقت التعديل
            if latest_product.get("updatedAt"):
                last_timestamp = int(latest_product["updatedAt"].timestamp() * 1000)
            elif latest_product.get("createdAt"):
                last_timestamp = int(latest_product["createdAt"].timestamp() * 1000)
            elif latest_product.get("_id"):
                # استخدام ObjectId timestamp كحل بديل
                last_timestamp = int(latest_product["_id"].generation_time.timestamp() * 1000)
        
        # 3. المنتجات منخفضة المخزون
        low_stock_count = await products_collection.count_documents({
            "stock_quantity": {"$lte": 5}
        })
        
        return {
            "productCount": product_count,
            "lastTimestamp": last_timestamp,
            "lowStockCount": low_stock_count,
            "serverTime": int(time.time() * 1000),
            "success": True
        }
        
    except Exception as e:
        print(f"Error in quick-check: {e}")
        return {
            "productCount": 0,
            "lastTimestamp": 0,
            "lowStockCount": 0,
            "serverTime": int(time.time() * 1000),
            "success": False,
            "error": str(e)
        }

@app.get("/api/products/sync-status")
async def sync_status():
    """حالة المزامنة الحالية"""
    try:
        # جلب بعض الإحصائيات الأساسية
        stats_cursor = products_collection.aggregate([
            {
                "$group": {
                    "_id": None,
                    "totalProducts": {"$sum": 1},
                    "totalQuantity": {"$sum": "$stock_quantity"},
                    "totalValue": {"$sum": {"$multiply": ["$stock_quantity", "$price"]}}
                }
            }
        ])
        
        stats = await stats_cursor.to_list(length=1)
        
        if stats:
            stats_data = stats[0]
        else:
            stats_data = {"totalProducts": 0, "totalQuantity": 0, "totalValue": 0}
        
        # جلب أحدث 5 منتجات معدلة
        recent_updates = []
        async for product in products_collection.find(
            {},
            {
                "_id": 1,
                "name": 1,
                "stock_quantity": 1,
                "updatedAt": 1,
                "createdAt": 1
            }
        ).sort([("$natural", -1)]).limit(5):
            
            # تحويل التواريخ
            updated_at = product.get("updatedAt")
            created_at = product.get("createdAt")
            
            if updated_at:
                last_modified = updated_at
            else:
                last_modified = created_at or product["_id"].generation_time
            
            recent_updates.append({
                "id": str(product["_id"]),
                "name": product.get("name", "غير معروف"),
                "quantity": product.get("stock_quantity", 0),
                "lastModified": last_modified.isoformat() if isinstance(last_modified, datetime) 
                              else last_modified.strftime("%Y-%m-%dT%H:%M:%SZ")
            })
        
        return {
            "stats": {
                "totalProducts": stats_data.get("totalProducts", 0),
                "totalQuantity": stats_data.get("totalQuantity", 0),
                "totalValue": stats_data.get("totalValue", 0)
            },
            "recentUpdates": recent_updates,
            "lastSync": datetime.utcnow().isoformat(),
            "success": True
        }
        
    except Exception as e:
        print(f"Error in sync-status: {e}")
        return {
            "stats": {"totalProducts": 0, "totalQuantity": 0, "totalValue": 0},
            "recentUpdates": [],
            "lastSync": datetime.utcnow().isoformat(),
            "success": False,
            "error": str(e)
        }

@app.head("/api/products/ping")
async def ping_products():
    """طريقة HEAD للتحقق من توفر الخدمة فقط"""
    return {"message": "Service is available"}


@app.middleware("http")
async def add_last_modified_header(request, call_next):
    """إضافة Last-Modified header لطلبات المنتجات"""
    response = await call_next(request)
    
    if request.url.path.startswith("/api/products") and request.method == "GET":
        try:
            # محاولة جلب آخر وقت تحديث
            pipeline = [
                {"$sort": {"$natural": -1}},
                {"$limit": 1},
                {"$project": {
                    "last_modified": {
                        "$cond": {
                            "if": {"$gt": ["$updated_at", "$created_at"]},
                            "then": "$updated_at",
                            "else": "$created_at"
                        }
                    }
                }}
            ]
            
            async for result in products_collection.aggregate(pipeline):
                if result.get("last_modified") and isinstance(result["last_modified"], datetime):
                    http_date = formatdate(time.mktime(result["last_modified"].timetuple()))
                    response.headers["Last-Modified"] = http_date
                    break
                    
        except Exception:
            pass
    
    return response


@app.get("/barcode", include_in_schema=False)
async def root():
    """Return the frontend index.html when visiting the root path."""
    # Prefer a project-root `index.html` if the user attached a custom UI there.
    repo_root_index = os.path.join(os.path.dirname(__file__), "barcodecreator.html")
    static_index = os.path.join(static_dir, "barcodecreator.html") if static_dir else None

    if os.path.isfile(repo_root_index):
        return FileResponse(repo_root_index)

    if static_index and os.path.isfile(static_index):
        return FileResponse(static_index)

    return {"detail": "Frontend not found"}
@app.get("/login", include_in_schema=False)
async def root():
    """Return the frontend index.html when visiting the root path."""
    # Prefer a project-root `index.html` if the user attached a custom UI there.
    repo_root_index = os.path.join(os.path.dirname(__file__), "login.html")
    static_index = os.path.join(static_dir, "login.html") if static_dir else None

    if os.path.isfile(repo_root_index):
        return FileResponse(repo_root_index)

    if static_index and os.path.isfile(static_index):
        return FileResponse(static_index)

    return {"detail": "Frontend not found"}
@app.get("/conectseller/", include_in_schema=False)
async def root():
    """Return the frontend index.html when visiting the root path."""
    # Prefer a project-root `index.html` if the user attached a custom UI there.
    repo_root_index = os.path.join(os.path.dirname(__file__), "conectseller.html")
    static_index = os.path.join(static_dir, "conectseller.html") if static_dir else None

    if os.path.isfile(repo_root_index):
        return FileResponse(repo_root_index)

    if static_index and os.path.isfile(static_index):
        return FileResponse(static_index)

    return {"detail": "Frontend not found"}

@app.post("/product/", response_description="إضافة منتج جديد للمخزون")
async def create_product(product: Product = Body(...)):
    product = jsonable_encoder(product)
    new_product = await products_collection.insert_one(product)
    created_product = await products_collection.find_one({"_id": new_product.inserted_id})
    # تحويل _id من ObjectId إلى string لكي يقبله الـ JSON
    created_product["_id"] = str(created_product["_id"])
    return created_product


@app.post("/products", response_description="إضافة منتج جديد (مرن)")
async def create_product_flexible(payload: dict = Body(...)):
    """Fallback endpoint that accepts flexible product JSON from the legacy frontend."""
    # If payload contains base64 image data under `imageData`, save it to disk and replace with `imagePath`.
    if isinstance(payload, dict) and payload.get('imageData'):
        img_data = payload.pop('imageData')
        try:
            # data URL may be like: data:image/jpeg;base64,/9j/...
            if isinstance(img_data, str) and img_data.startswith('data:'):
                _meta, b64 = img_data.split(',', 1)
                meta = _meta.split(';')[0]  # e.g. data:image/jpeg
                mime = meta.split(':')[1] if ':' in meta else 'image/jpeg'
            else:
                b64 = img_data
                mime = 'image/jpeg'

            binary = base64.b64decode(b64)
            ext = 'jpg'
            if 'png' in mime:
                ext = 'png'
            elif 'gif' in mime:
                ext = 'gif'
            filename = f"{uuid.uuid4().hex}.{ext}"
            path = os.path.join(images_dir, filename)
            with open(path, 'wb') as f:
                f.write(binary)
            # public path served at /images/<filename>
            payload['imagePath'] = f"/images/{filename}"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image data: {e}")

    doc = jsonable_encoder(payload)
    new_product = await products_collection.insert_one(doc)
    created = await products_collection.find_one({"_id": new_product.inserted_id})
    if created and created.get("_id"):
        created["_id"] = str(created["_id"])
    return created


@app.post("/category/", response_description="إضافة صنف جديد")
async def create_category(category: Category = Body(...)):
    category = jsonable_encoder(category)
    new_cat = await categories_collection.insert_one(category)
    created = await categories_collection.find_one({"_id": new_cat.inserted_id})
    created["_id"] = str(created["_id"])
    return created


def to_object_id(id_str: str):
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")

@app.get("/products", response_description="جلب المنتجات مع فلترة")
async def list_products(
    q: Optional[str] = Query(None, description="بحث في الاسم أو الوصف"),
    category_id: Optional[int] = Query(None, description="فلترة بحسب category_id"),
    low_stock: Optional[bool] = Query(False, description="عرض فقط العناصر منخفضة المخزون"),
    limit: int = Query(50, ge=1, le=100, description="عدد النتائج"),
    skip: int = Query(0, ge=0, description="تخطي"),
):
    """Return products with optional search and filters. Also attaches category info when available."""
    pipeline = []

    # Filters
    match = {}
    if q:
        match.update({
            "$or": [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]
        })
    if category_id is not None:
        match.update({"category_id": category_id})
    if low_stock:
        # threshold can be adjusted
        match.update({"stock_quantity": {"$lte": 5}})

    if match:
        pipeline.append({"$match": match})

    # Attach category info (if any)
    pipeline.append({
        "$lookup": {
            "from": "categories",
            "localField": "category_id",
            "foreignField": "id",
            "as": "category"
        }
    })
    pipeline.append({"$unwind": {"path": "$category", "preserveNullAndEmptyArrays": True}})

    # Pagination
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": limit})

    cursor = products_collection.aggregate(pipeline)
    products = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"]) if doc.get("_id") is not None else None
        # simplify category to name only to match frontend expectations
        if isinstance(doc.get("category"), dict):
            doc["category_name"] = doc["category"].get("name")
            # keep category_id as-is as well
            del doc["category"]
        products.append(doc)

    return products


@app.get("/categories", response_description="جلب كافة الأصناف")
async def list_categories():
    cats = []
    cursor = categories_collection.find()
    async for c in cursor:
        c["_id"] = str(c["_id"]) if c.get("_id") is not None else None
        cats.append(c)
    return cats

@app.delete('/category/{category_name}', response_description="حذف صنف")
async def delete_category(category_name: str = Path(...)):
    res = await categories_collection.delete_one({"name": category_name})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"deleted": True}
@app.patch("/product/{product_id}", response_description="تحديث منتج جزئياً")
async def update_product(product_id: str = Path(...), updates: dict = Body(...)):
    oid = to_object_id(product_id)
    # Prevent updating _id
    updates.pop("_id", None)
    # If client sent base64 `imageData`, save file and set `imagePath` instead
    if isinstance(updates, dict) and updates.get('imageData'):
        img_data = updates.pop('imageData')
        try:
            if isinstance(img_data, str) and img_data.startswith('data:'):
                _meta, b64 = img_data.split(',', 1)
                meta = _meta.split(';')[0]
                mime = meta.split(':')[1] if ':' in meta else 'image/jpeg'
            else:
                b64 = img_data
                mime = 'image/jpeg'

            binary = base64.b64decode(b64)
            ext = 'jpg'
            if 'png' in mime:
                ext = 'png'
            elif 'gif' in mime:
                ext = 'gif'
            filename = f"{uuid.uuid4().hex}.{ext}"
            path = os.path.join(images_dir, filename)
            with open(path, 'wb') as f:
                f.write(binary)
            updates['imagePath'] = f"/images/{filename}"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image data: {e}")
    result = await products_collection.find_one_and_update(
        {"_id": oid},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    result["_id"] = str(result["_id"])
    return result


@app.delete("/product/{product_id}", response_description="حذف منتج")
async def delete_product(product_id: str = Path(...)):
    oid = to_object_id(product_id)
    res = await products_collection.delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": True}


@app.post("/product/{product_id}/sell", response_description="سجل بيع وخصم الكمية")
async def sell_product(product_id: str = Path(...), payload: dict = Body(...)):
    qty = int(payload.get("quantity", 0))
    price = payload.get("price")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    oid = to_object_id(product_id)

    # Atomic decrement only if enough stock
    updated = await products_collection.find_one_and_update(
        {"_id": oid, "stock_quantity": {"$gte": qty}},
        {"$inc": {"stock_quantity": -qty}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=400, detail="Insufficient stock or product not found")

    # create transaction record
    tx = {
        "product_id": oid,
        "type": "sale",
        "quantity": qty,
        "price": float(price) if price is not None else None,
        "timestamp": datetime.utcnow(),
    }
    inserted = await transactions_collection.insert_one(tx)
    tx["_id"] = str(inserted.inserted_id)
    updated["_id"] = str(updated["_id"]) if updated.get("_id") else None
    return {"product": updated, "transaction": tx}


@app.post("/product/{product_id}/purchase", response_description="سجل عملية شراء وزيادة الكمية")
async def purchase_product(product_id: str = Path(...), payload: dict = Body(...)):
    qty = int(payload.get("quantity", 0))
    price = payload.get("price")
    if qty >= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    oid = to_object_id(product_id)

    updated = await products_collection.find_one_and_update(
        {"_id": oid},
        {"$inc": {"stock_quantity": qty}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")

    tx = {
        "product_id": oid,
        "type": "purchase",
        "quantity": qty,
        "price": float(price) if price is not None else None,
        "timestamp": datetime.utcnow(),
    }
    inserted = await transactions_collection.insert_one(tx)
    tx["_id"] = str(inserted.inserted_id)
    updated["_id"] = str(updated["_id"]) if updated.get("_id") else None
    return {"product": updated, "transaction": tx}


@app.get("/transactions", response_description="جلب الحركات مع فلترة")
async def list_transactions(
    product_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
):
    q = {}
    if product_id:
        try:
            q["product_id"] = ObjectId(product_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid product_id")
    if type:
        q["type"] = type
    if date_from or date_to:
        q["timestamp"] = {}
        if date_from:
            q["timestamp"]["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            q["timestamp"]["$lte"] = datetime.fromisoformat(date_to)

    cursor = transactions_collection.find(q).skip(skip).limit(limit)
    results = []
    async for t in cursor:
        t["_id"] = str(t["_id"]) if t.get("_id") else None
        if isinstance(t.get("product_id"), ObjectId):
            t["product_id"] = str(t["product_id"])
        results.append(t)
    return results


@app.delete("/products", response_description="حذف جميع المنتجات والحركات")
async def delete_all_products():
    """Delete all products, transactions and optionally categories (use with care)."""
    await products_collection.delete_many({})
    await transactions_collection.delete_many({})
    return {"deleted": True}


@app.post("/import", response_description="استيراد ومزامنة البيانات")
async def import_data(payload: dict = Body(...)):
    """Import JSON payload and replace collections with provided data.

    Expected keys: `products` (list), `transactions` (list), `categories` (list).
    This will clear the corresponding collections and insert provided documents.
    The endpoint strips any incoming `_id` fields so MongoDB will generate new ObjectIds.
    Returned payload contains the newly inserted documents with their assigned `_id` strings.
    """
    try:
        products_docs = payload.get('products', []) or []
        transactions_docs = payload.get('transactions', []) or []
        categories_docs = payload.get('categories', []) or []

        # Clear existing data
        await products_collection.delete_many({})
        await transactions_collection.delete_many({})
        await categories_collection.delete_many({})

        def prepare(doc):
            if isinstance(doc, dict):
                d = dict(doc)
                d.pop('_id', None)
                return d
            raise ValueError(f"Invalid document type: {type(doc).__name__}")

        inserted_products = []
        if products_docs:
            try:
                docs = [prepare(d) for d in products_docs]
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
            await products_collection.insert_many(docs)
            cursor = products_collection.find()
            async for p in cursor:
                p['_id'] = str(p['_id']) if p.get('_id') else None
                inserted_products.append(p)

        inserted_transactions = []
        if transactions_docs:
            try:
                docs = [prepare(d) for d in transactions_docs]
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
            await transactions_collection.insert_many(docs)
            cursor = transactions_collection.find()
            async for t in cursor:
                t['_id'] = str(t['_id']) if t.get('_id') else None
                if isinstance(t.get('product_id'), ObjectId):
                    t['product_id'] = str(t['product_id'])
                inserted_transactions.append(t)

        inserted_categories = []
        if categories_docs:
            try:
                docs = [prepare(d) for d in categories_docs]
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
            await categories_collection.insert_many(docs)
            cursor = categories_collection.find()
            async for c in cursor:
                c['_id'] = str(c['_id']) if c.get('_id') else None
                inserted_categories.append(c)

        return {
            'products': inserted_products,
            'transactions': inserted_transactions,
            'categories': inserted_categories,
        }
    except Exception as e:
        # Return a readable error to help debugging (development only)
        raise HTTPException(status_code=500, detail=str(e))
    

    # بيانات لوحة التحكم
@app.get("/api/dashboard/stats", response_description="إحصائيات لوحة التحكم")
async def get_dashboard_stats():
    """الحصول على إحصائيات لوحة التحكم"""
    
    # إحصائيات المنتجات
    total_products = await products_collection.count_documents({})
    low_stock_products = await products_collection.count_documents({"stock_quantity": {"$lte": 5}})
    
    # إحصائيات المبيعات
    pipeline = [
        {"$match": {"type": "sale"}},
        {"$group": {
            "_id": None,
            "total_sales": {"$sum": {"$multiply": ["$quantity", "$price"]}},
            "total_transactions": {"$sum": 1}
        }}
    ]
    
    sales_stats = await transactions_collection.aggregate(pipeline).to_list(1)
    total_sales = sales_stats[0]["total_sales"] if sales_stats else 0
    
    # إحصائيات الشهرية
    import calendar
    from datetime import datetime, timedelta
    
    current_month = datetime.utcnow().month
    current_year = datetime.utcnow().year
    
    monthly_sales = []
    for month in range(1, 13):
        start_date = datetime(current_year, month, 1)
        end_date = datetime(current_year, month, calendar.monthrange(current_year, month)[1])
        
        pipeline = [
            {"$match": {
                "type": "sale",
                "timestamp": {"$gte": start_date, "$lte": end_date}
            }},
            {"$group": {
                "_id": None,
                "monthly_sales": {"$sum": {"$multiply": ["$quantity", "$price"]}}
            }}
        ]
        
        result = await transactions_collection.aggregate(pipeline).to_list(1)
        monthly_sales.append(result[0]["monthly_sales"] if result else 0)
    
    # إحصائيات الفئات
    category_pipeline = [
        {"$group": {
            "_id": "$category_id",
            "count": {"$sum": 1}
        }},
        {"$lookup": {
            "from": "categories",
            "localField": "_id",
            "foreignField": "id",
            "as": "category"
        }},
        {"$unwind": "$category"},
        {"$project": {
            "name": "$category.name",
            "value": "$count"
        }}
    ]
    
    product_categories = await products_collection.aggregate(category_pipeline).to_list(10)
    
    return {
        "total_products": total_products,
        "low_stock_products": low_stock_products,
        "total_sales": total_sales,
        "total_customers": await vendors_collection.count_documents({}),
        "monthly_sales": monthly_sales,
        "product_categories": product_categories,
        "sales_trend": "up",
        "updated_at": datetime.utcnow().isoformat()
    }

# بيانات البائع
@app.get("/api/vendor/profile", response_description="ملف البائع الشخصي")
async def get_vendor_profile():
    """الحصول على ملف البائع الشخصي"""
    # في الواقع يجب استخدام التوكن للتحقق
    # هنا نعود بيانات بائع افتراضي للتنمية
    
    return {
        "id": "vendor_001",
        "name": "بائع تجريبي",
        "email": "vendor@example.com",
        "username": "vendor",
        "phone": "0912345678",
        "permissions": ["view_products", "add_products", "edit_products", "view_sales", "create_sales"],
        "role": "vendor",
        "created_at": "2024-01-01T00:00:00Z",
        "is_active": True
    }
