from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Category(BaseModel):
    id: Optional[int] = None
    name: str

class Product(BaseModel):
    id: Optional[int] = None
    name: str
    category_id: int # يربط المنتج بصنف معين
    description: Optional[str] = None
    price: float = Field(gt=0) # السعر يجب أن يكون أكبر من صفر
    stock_quantity: int = Field(ge=0) # الكمية لا يمكن أن تكون سالبة
    updatedAt: Optional[datetime] = None

class Transaction(BaseModel):
    id: Optional[int] = None
    product_id: Optional[str] = None
    type: str  # 'sale' or 'purchase'
    quantity: int
    price: Optional[float] = None
    timestamp: Optional[datetime] = None