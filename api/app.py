"""API REST de inventario para la tienda de Carla.

Los productos se guardan en products.csv (raíz del proyecto) para que
persistan entre sesiones.

Arranque (desde la raíz del proyecto):
    uvicorn api.app:app --reload
"""

import csv
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

PRODUCTS_FILE = Path(__file__).resolve().parent.parent / "products.csv"
FIELDS = ["id", "name", "quantity", "unit"]
DEFAULT_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class Product(BaseModel):
    id: int
    name: str
    quantity: float
    unit: str


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, description="Nombre del producto")
    quantity: float = Field(ge=0, description="Cantidad inicial en stock")
    unit: str = Field(min_length=1, description="Unidad de medida (unidades, kg, litros...)")

    @field_validator("name", "unit")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("no puede estar vacío")
        return value


class StockUpdate(BaseModel):
    delta: float = Field(description="Positivo para entradas de stock, negativo para salidas")

    @field_validator("delta")
    @classmethod
    def non_zero(cls, value: float) -> float:
        if value == 0:
            raise ValueError("delta no puede ser 0")
        return value


# ---------------------------------------------------------------------------
# Persistencia en CSV
# ---------------------------------------------------------------------------

def _format_number(value: float) -> str:
    """Escribe 30 en lugar de 30.0 cuando la cantidad es entera."""
    return str(int(value)) if float(value).is_integer() else str(value)


def read_products() -> list[dict]:
    if not PRODUCTS_FILE.exists():
        write_products([])
        return []
    with PRODUCTS_FILE.open(newline="", encoding="utf-8") as f:
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "quantity": float(row["quantity"]),
                "unit": row["unit"],
            }
            for row in csv.DictReader(f)
        ]


def write_products(products: list[dict]) -> None:
    # Escritura atómica: fichero temporal + reemplazo, para no dejar el CSV a medias.
    fd, tmp_path = tempfile.mkstemp(dir=PRODUCTS_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for p in products:
                writer.writerow({**p, "quantity": _format_number(p["quantity"])})
        os.replace(tmp_path, PRODUCTS_FILE)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Inventario - Suministros para cafeterías",
    description="API de inventario que usa el agente de IA como conjunto de herramientas.",
)


@app.get("/inventory", response_model=list[Product])
def list_inventory():
    """Devuelve la lista completa de productos."""
    return read_products()


@app.post("/inventory", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate):
    """Añade un nuevo producto al inventario."""
    products = read_products()
    if any(p["name"].lower() == product.name.lower() for p in products):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un producto llamado '{product.name}'.",
        )
    new_product = {
        "id": max((p["id"] for p in products), default=0) + 1,
        "name": product.name,
        "quantity": product.quantity,
        "unit": product.unit,
    }
    products.append(new_product)
    write_products(products)
    return new_product


@app.get("/inventory/alerts", response_model=list[Product])
def low_stock_alerts(
    threshold: float = Query(
        DEFAULT_THRESHOLD, ge=0, description="Umbral de stock bajo (por defecto 10)"
    ),
):
    """Devuelve los productos cuya cantidad está por debajo del umbral."""
    return [p for p in read_products() if p["quantity"] < threshold]


@app.patch("/inventory/{product_id}", response_model=Product)
def update_stock(product_id: int, update: StockUpdate):
    """Suma `delta` al stock del producto (positivo = entrada, negativo = salida)."""
    products = read_products()
    product = next((p for p in products if p["id"] == product_id), None)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe ningún producto con id {product_id}.",
        )
    new_quantity = product["quantity"] + update.delta
    if new_quantity < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stock insuficiente de '{product['name']}': hay "
                f"{_format_number(product['quantity'])} {product['unit']} y se intentó "
                f"restar {_format_number(-update.delta)}."
            ),
        )
    product["quantity"] = round(new_quantity, 3)
    write_products(products)
    return product
