# importamos las dependencias y configuraciones necesarias para desarrollar tu API RESTful usando FastAPI, y estás preparando 
# tu entorno para que el backend tenga las capacidades claves

#Framework principal
from fastapi import FastAPI, HTTPException, Depends, Header, Query, Path
#respuestas de la API
from fastapi.responses import FileResponse, JSONResponse
#dependencias para manejar CORS
from fastapi.middleware.cors import CORSMiddleware
import httpx
#validaciones de datos
from pydantic import BaseModel, validator
import stripe, os
#dependencias para manejar archivos estáticos
from fastapi.staticfiles import StaticFiles
import os
import json
#dependencias para cargar variables de entorno
from dotenv import load_dotenv

# Cargamos las variables de entorno
app = FastAPI(
    title="integracion",
    description="toda la integracion",
    version="1.0.0",
)

# CORS para el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Datos de usuarios hardcodeados
USERS = [
    {"user": "javier_thompson", "password": "aONF4d6aNBIxRjlgjBRRzrS", "role": "admin"},
    {"user": "ignacio_tapia", "password": "f7rWChmQS1JYfThT", "role": "maintainer"},
    {"user": "stripe_sa", "password": "dzkQqDL9XZH33YDzhmsf", "role": "service_account"},
    {"user": "Admin", "password": "1234", "role": "admin"},
]

DB_FILE = "db/productos.json"

# Montar DB
app.mount("/db", StaticFiles(directory="db"), name="db")

load_dotenv()

# Variables de entorno
API_BASE = os.getenv('API_BASE')
FIXED_TOKEN = os.getenv('FIXED_TOKEN')
VENDOR_ALLOW_TOKEN = os.getenv("VENDOR_ALLOW_TOKEN")
VENDOR_DENY_TOKEN  = os.getenv("VENDOR_DENY_TOKEN")
URL = os.getenv("URL")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Info Productos para Stripe
class Item(BaseModel):
    id: str
    name: str
    price: int
    quantity: int
    currency: str

    @validator("currency")
    def valid_currency(cls, v):
        if v not in ("clp", "usd"):
            raise ValueError("currency debe ser 'clp' o 'usd'")
        return v

# Endpoint de Stripe
@app.post("/create-checkout-session", tags=["Stripe"])
async def createCheckoutSession(items: list[Item]):
    try:
        # Verifica que la lista de items no esté vacía
        line_items = []
        for item in items:
            # Si la moneda es USD, convertimos a CLP
            line_items.append({
                "price_data": {
                    "currency": "clp", 
                    "unit_amount": item.price,
                    "product_data": {"name": item.name}
                },
                "quantity": item.quantity
            })
            # Si la moneda es USD, convertimos a CLP
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=line_items,
            #metadata={"items": str(items)},
            success_url=f"{URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{URL}/cancel"
        )
        # Devuelve la URL de Stripe
        return {"url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Verifica el token de autenticación
def verifyToken(
    x_authentication: str = Header(None, alias="x-authentication")
):
    """
    Sólo acepta el FIXED_TOKEN para autenticar cualquier endpoint.
    """
    if x_authentication != FIXED_TOKEN:
        raise HTTPException(403, "Token inválido")
    return x_authentication

# Verifica el token de empresa externa
def verifyVendorToken(
    x_vendor_token: str = Header(None, alias="x-vendor-token")
):
    """
    Sólo permite el VENDOR_ALLOW_TOKEN.
    """
    if x_vendor_token != VENDOR_ALLOW_TOKEN:
        raise HTTPException(403, "No tienes permiso para este recurso")
    return x_vendor_token

# Proxy de todos los endpoints bajo /data/*
# Se encarga de redirigir las peticiones a la API de I. de Plataformas
# y devolver la respuesta al cliente.
# Se usa para evitar CORS y manejar la autenticación
# de forma centralizada.
async def proxyGet(path: str, token: str):
    headers = {"x-authentication": token}
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}{path}", headers=headers)
        return JSONResponse(status_code=r.status_code, content=r.json())


async def proxyPost(path: str, body: dict, token: str):
    headers = {"x-authentication": token}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}{path}", json=body, headers=headers)
        return JSONResponse(status_code=r.status_code, content=r.json())
    
async def proxyPut(path: str, headers: dict):
    async with httpx.AsyncClient() as client:
        r = await client.put(f"{API_BASE}{path}", headers=headers)
        return JSONResponse(status_code=r.status_code, content=r.json())

# Endpoint de autenticación
@app.post("/autenticacion", tags=["Auth"])
async def login(creds: dict):
    """Valida user/password y devuelve token + role"""
    user = creds.get("user")
    pwd  = creds.get("password")
    for u in USERS:
        if u["user"] == user and u["password"] == pwd:
            if u["role"] == "service_account":
                vendor_tok = VENDOR_DENY_TOKEN
            else:
                vendor_tok = VENDOR_ALLOW_TOKEN
            return {"token": FIXED_TOKEN, "role": u["role"], "vendorToken": vendor_tok}
    raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
# Endpoint de Divisas
@app.get("/currency", tags=["Divisas"])
async def get_appnexus_rate(
    code: str = Query(..., min_length=3, max_length=3, description="Código ISO de la moneda origen (ej. CLP)")
):
    """
    Devuelve la tasa CLP → USD según AppNexus (rate_per_usd).
    """
    url = f"https://api.appnexus.com/currency?code={code}&show_rate=true"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
    data = r.json()
    resp = data.get("response", {})
    if resp.get("status") != "OK":
        raise HTTPException(status_code=502, detail="Error al consultar tasa AppNexus")
    rate_per_usd = float(resp["currency"]["rate_per_usd"])
    return {"rate": 1 / rate_per_usd}

# Endpoint de productos
@app.get("/data/articulos", dependencies=[Depends(verifyToken)], tags=["Articulos"])
async def getArticulos(token: str = Depends(verifyToken)):
    return await proxyGet("/data/articulos", token)

# Endpoint de un producto
@app.get("/data/articulos/{aid}", dependencies=[Depends(verifyToken)], tags=["Articulos"])
async def getArticulo(aid: str, token: str = Depends(verifyToken)):
    return await proxyGet(f"/data/articulos/{aid}", token)

# Endpoint de sucursales
@app.get("/data/sucursales", dependencies=[Depends(verifyToken)],tags=["Sucursales"])
async def getSucursales(token: str = Depends(verifyToken)):
    return await proxyGet("/data/sucursales", token)

# Endpoint de sucursal
@app.get("/data/sucursales/{sid}", dependencies=[Depends(verifyToken)], tags=["Sucursales"])
async def getSucursal(sid: str, token: str = Depends(verifyToken)):
    return await proxyGet(f"/data/sucursales/{sid}", token)

# Endpoint de vendedores
@app.get("/data/vendedores", dependencies=[Depends(verifyToken), Depends(verifyVendorToken)], tags=["Vendedores"])
async def getVendedor(token: str = Depends(verifyToken)):
    return await proxyGet(f"/data/vendedores", token)

# Endpoint de un vendedor
@app.get("/data/vendedores/{vid}", dependencies=[Depends(verifyToken), Depends(verifyVendorToken)], tags=["Vendedores"])
async def getVendedor(vid: str, token: str = Depends(verifyToken)):
    return await proxyGet(f"/data/vendedores/{vid}", token)

# Endpoint de agregado de venta
@app.put("/data/articulos/venta/{aid}", dependencies=[Depends(verifyToken)], tags=["Ventas"])
async def postVenta(aid: str, cantidad: int = Query(...), token: str = Depends(verifyToken)):
    return await proxyPut(f"/data/articulos/venta/{aid}?cantidad={cantidad}", headers={"x-authentication": token})

# Endpoint de agregado de venta local
@app.put("/data/local/articulos/venta/{aid}", tags=["Ventas"])
async def venta_local(
    aid: str = Path(..., description="ID del artículo local"),
    cantidad: int = Query(..., gt=0, description="Cantidad a descontar")
):
    try:
        with open(DB_FILE, "r+", encoding="utf-8") as f:
            productos = json.load(f)

            for prod in productos:
                if prod.get("id") == aid:
                    if prod["stock"] < cantidad:
                        raise HTTPException(400, "Stock insuficiente")
                    prod["stock"] -= cantidad

                    f.seek(0)
                    json.dump(productos, f, ensure_ascii=False, indent=2)
                    f.truncate()

                    return {"message": f"Venta local exitosa. Stock nuevo: {prod['stock']}"}

            raise HTTPException(404, "Artículo local no encontrado")

    except HTTPException:
        raise
    except Exception as e:
        print("Error en venta_local:", e)
        raise HTTPException(500, f"Error interno al procesar venta: {e}")

# Sirve la web estática
# HTML , CSS, JS, imágenes, etc.
@app.get("/", tags=["Web"])
async def HTML():
    return FileResponse("index.html")

# CSS
@app.get("/styles.css", response_class=FileResponse, tags=["Web"])
async def CSS():
    return FileResponse(path="styles.css", media_type="text/css",headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"})

# JS
@app.get("/script.js", tags=["Web"])
async def JS():
    return FileResponse("script.js", media_type="application/javascript",headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0","Pragma": "no-cache"})

# Página de éxito
@app.get("/success", tags=["Web"])
async def success_page():
    return FileResponse("success.html", media_type="text/html")

# Página de cancelación
@app.get("/cancel", tags=["Web"])
async def cancel_page():
    return FileResponse("cancel.html", media_type="text/html")

# Code Stripe
@app.get("/config", tags=["Stripe"])
async def getStripePublicKey():
    public_key = os.getenv("STRIPE_PUBLISHABLE_KEY")
    if not public_key:
        raise HTTPException(status_code=500, detail="Clave pública de Stripe no configurada")
    return {"publicKey": public_key}
