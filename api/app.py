import csv
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

app = FastAPI()

# Keep the data file at the repository root, regardless of the process cwd.
# The environment override lets tests use an isolated CSV without touching user data.
PRODUCTS_CSV = Path(
    os.environ.get(
        "INVENTORY_CSV_PATH",
        str(Path(__file__).resolve().parent.parent / "products.csv"),
    )
)


class ProductCreate(BaseModel):
    name: str
    quantity: float = Field(ge=0, allow_inf_nan=False)
    unit: str

    @field_validator("name", "unit")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("no puede estar vacío")
        return value


class InventoryAdjustment(BaseModel):
    delta: float = Field(allow_inf_nan=False)


def _display_quantity(quantity: float) -> int | float:
    """Keep whole quantities as JSON integers while supporting fractions."""
    return int(quantity) if math.isfinite(quantity) and quantity.is_integer() else quantity


@app.get("/inventory")
def list_inventory():
    """Return inventory rows from the root-level CSV as JSON objects."""
    try:
        with PRODUCTS_CSV.open("r", newline="", encoding="utf-8") as csv_file:
            rows = csv.DictReader(csv_file)
            products = []
            for row in rows:
                quantity = float(row["quantity"])
                products.append(
                    {
                        "id": int(row["id"]),
                        "name": row["name"],
                        "quantity": _display_quantity(quantity),
                        "unit": row["unit"],
                    }
                )
            return products
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=500,
            detail=f"No se encontró el archivo de inventario: {PRODUCTS_CSV}",
        ) from error
    except (KeyError, ValueError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"El archivo de inventario contiene una fila inválida: {error}",
        ) from error


@app.get("/inventory/alerts")
def list_inventory_alerts(
    threshold: float = Query(default=10, ge=0, allow_inf_nan=False),
):
    """Return products whose current quantity is below the alert threshold."""
    return [
        product
        for product in list_inventory()
        if product["quantity"] < threshold
    ]


@app.post("/inventory", status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate):
    """Add a new product row without replacing existing inventory."""
    try:
        with PRODUCTS_CSV.open("r", newline="", encoding="utf-8") as csv_file:
            existing_products = list(csv.DictReader(csv_file))
        next_id = max((int(row["id"]) for row in existing_products), default=0) + 1

        created = {
            "id": next_id,
            "name": product.name,
            "quantity": _display_quantity(product.quantity),
            "unit": product.unit,
        }
        needs_header = not PRODUCTS_CSV.exists() or PRODUCTS_CSV.stat().st_size == 0
        with PRODUCTS_CSV.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["id", "name", "quantity", "unit"])
            if needs_header:
                writer.writeheader()
            writer.writerow(created)
        return created
    except (OSError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo guardar el producto en el inventario: {error}",
        ) from error


@app.patch("/inventory/{product_id}")
def adjust_inventory(product_id: int, adjustment: InventoryAdjustment):
    """Apply a stock delta and atomically persist the updated inventory."""
    try:
        with PRODUCTS_CSV.open("r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = reader.fieldnames
            products = list(reader)

        target = next(
            (row for row in products if int(row["id"]) == product_id),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No existe un producto con id {product_id}.",
            )

        new_quantity = float(target["quantity"]) + adjustment.delta
        if new_quantity < 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El ajuste dejaría el stock de '{target['name']}' por debajo de cero."
                ),
            )

        target["quantity"] = str(_display_quantity(new_quantity))
        with NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=PRODUCTS_CSV.parent,
            delete=False,
        ) as temporary_file:
            writer = csv.DictWriter(temporary_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(products)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(PRODUCTS_CSV)

        return {
            "id": int(target["id"]),
            "name": target["name"],
            "quantity": _display_quantity(new_quantity),
            "unit": target["unit"],
        }
    except HTTPException:
        raise
    except (OSError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo actualizar el inventario: {error}",
        ) from error