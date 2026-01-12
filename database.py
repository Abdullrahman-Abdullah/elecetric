from motor.motor_asyncio import AsyncIOMotorClient

MONGO_DETAILS = "mongodb+srv://electric_shop:aabbdd20@cluster0.kzpipyw.mongodb.net/?appName=Cluster0"

client = AsyncIOMotorClient(MONGO_DETAILS)

# قاعدة بيانات المحل
database = client.electric_shop_db

vendors_collection = database.get_collection("vendors")

# مجموعة المنتجات (Collection)
products_collection = database.get_collection("products")
# مجموعة الحركات (المعاملات) لتسجيل المبيعات/المشتريات
transactions_collection = database.get_collection("transactions")
# مجموعة الأصناف (Categories)
categories_collection = database.get_collection("categories")