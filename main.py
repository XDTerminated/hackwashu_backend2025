from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import asyncpg
import os
from dotenv import load_dotenv
import jwt
from jwt import PyJWKClient

load_dotenv()

app = FastAPI(title="Pomodoro Patch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:1420",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:1420",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


DATABASE_URL = os.getenv("DATABASE_URL")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")

jwks_client = PyJWKClient(CLERK_JWKS_URL)


async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()


async def verify_clerk_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")

        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token, signing_key.key, algorithms=["RS256"], options={"verify_exp": True}
        )

        email = None

        if "primary_email" in payload:
            email = payload["primary_email"]
        elif "email" in payload:
            email = payload["email"]
        elif "email_addresses" in payload and len(payload["email_addresses"]) > 0:
            email = payload["email_addresses"][0]

        if not email:
            print("JWT Payload:", payload)
            raise HTTPException(
                status_code=401,
                detail="Email not found in token. Available claims: "
                + ", ".join(payload.keys()),
            )

        return email

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    money: float = 0.0


class UsernameUpdate(BaseModel):
    new_username: str


class SeedPacketCreate(BaseModel):
    cost: float
    game: str


class PlantCreate(BaseModel):
    plant_type: str
    size: float
    rarity: str
    x: Optional[float] = None
    y: Optional[float] = None
    max_growth_time: datetime


class PlantPosition(BaseModel):
    x: float
    y: float


class MoneyUpdate(BaseModel):
    amount: float


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Pomodoro Patch API"}


@app.post("/users/", status_code=201)
async def create_user(
    user: UserCreate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if user.email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot create user with different email"
        )

    try:
        await conn.execute(
            'INSERT INTO "user" (username, email, money) VALUES ($1, $2, $3)',
            user.username,
            user.email,
            user.money,
        )
        return {"message": "User created successfully", "email": user.email}
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=400, detail="User with this email already exists"
        )


@app.delete("/users/{email}")
async def delete_user(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot delete another user's account"
        )

    async with conn.transaction():
        await conn.execute("DELETE FROM inventory WHERE email = $1", email)

        seed_packets = await conn.fetch(
            "SELECT seed_packet_id FROM seed_packet WHERE email = $1", email
        )
        for sp in seed_packets:
            await conn.execute(
                "DELETE FROM seed_packet WHERE seed_packet_id = $1",
                sp["seed_packet_id"],
            )

        plants = await conn.fetch("SELECT plant_id FROM plant WHERE email = $1", email)
        for p in plants:
            await conn.execute("DELETE FROM plant WHERE plant_id = $1", p["plant_id"])

        result = await conn.execute('DELETE FROM "user" WHERE email = $1', email)

        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted successfully"}


@app.patch("/users/{email}/username")
async def update_username(
    email: str,
    update: UsernameUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot update another user's username"
        )

    result = await conn.execute(
        'UPDATE "user" SET username = $1 WHERE email = $2', update.new_username, email
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "message": "Username updated successfully",
        "new_username": update.new_username,
    }


@app.post("/users/{email}/seed-packets/", status_code=201)
async def add_seed_packet(
    email: str,
    seed_packet: SeedPacketCreate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's inventory"
        )

    async with conn.transaction():
        user = await conn.fetchrow('SELECT * FROM "user" WHERE email = $1', email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        seed_packet_id = await conn.fetchval(
            "INSERT INTO seed_packet (cost, game, email) VALUES ($1, $2, $3) RETURNING seed_packet_id",
            seed_packet.cost,
            seed_packet.game,
            email,
        )

        await conn.execute(
            "INSERT INTO inventory (email, seed_packet_id, plant_id) VALUES ($1, $2, NULL)",
            email,
            seed_packet_id,
        )

    return {
        "message": "Seed packet added to inventory",
        "seed_packet_id": seed_packet_id,
    }


@app.delete("/users/{email}/seed-packets/{seed_packet_id}")
async def remove_seed_packet(
    email: str,
    seed_packet_id: int,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's inventory"
        )

    async with conn.transaction():
        inventory_item = await conn.fetchrow(
            "SELECT * FROM inventory WHERE email = $1 AND seed_packet_id = $2",
            email,
            seed_packet_id,
        )

        if not inventory_item:
            raise HTTPException(
                status_code=404, detail="Seed packet not found in inventory"
            )

        await conn.execute(
            "DELETE FROM inventory WHERE email = $1 AND seed_packet_id = $2",
            email,
            seed_packet_id,
        )

        await conn.execute(
            "DELETE FROM seed_packet WHERE seed_packet_id = $1", seed_packet_id
        )

    return {"message": "Seed packet removed from inventory"}


@app.post("/users/{email}/plants/", status_code=201)
async def create_plant(
    email: str,
    plant: PlantCreate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's inventory"
        )

    async with conn.transaction():
        user = await conn.fetchrow('SELECT * FROM "user" WHERE email = $1', email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        plant_id = await conn.fetchval(
            "INSERT INTO plant (plant_type, size, rarity, x, y, max_growth_time, email) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING plant_id",
            plant.plant_type,
            plant.size,
            plant.rarity,
            plant.x,
            plant.y,
            plant.max_growth_time,
            email,
        )

        await conn.execute(
            "INSERT INTO inventory (email, seed_packet_id, plant_id) VALUES ($1, NULL, $2)",
            email,
            plant_id,
        )

    return {"message": "Plant created and added to inventory", "plant_id": plant_id}


@app.patch("/users/{email}/plants/{plant_id}/plant")
async def plant_plant(
    email: str,
    plant_id: int,
    position: PlantPosition,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    inventory_item = await conn.fetchrow(
        "SELECT * FROM inventory WHERE email = $1 AND plant_id = $2", email, plant_id
    )

    if not inventory_item:
        raise HTTPException(status_code=404, detail="Plant not found in inventory")

    result = await conn.execute(
        "UPDATE plant SET x = $1, y = $2 WHERE plant_id = $3 AND email = $4",
        position.x,
        position.y,
        plant_id,
        email,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Plant not found")

    return {"message": "Plant planted successfully", "x": position.x, "y": position.y}


@app.patch("/users/{email}/plants/{plant_id}/shovel")
async def shovel_plant(
    email: str,
    plant_id: int,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    inventory_item = await conn.fetchrow(
        "SELECT * FROM inventory WHERE email = $1 AND plant_id = $2", email, plant_id
    )

    if not inventory_item:
        raise HTTPException(status_code=404, detail="Plant not found in inventory")

    result = await conn.execute(
        "UPDATE plant SET x = NULL, y = NULL WHERE plant_id = $1 AND email = $2",
        plant_id,
        email,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Plant not found")

    return {"message": "Plant shoveled back to inventory"}


@app.delete("/users/{email}/plants/{plant_id}")
async def remove_plant(
    email: str,
    plant_id: int,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's inventory"
        )

    async with conn.transaction():
        inventory_item = await conn.fetchrow(
            "SELECT * FROM inventory WHERE email = $1 AND plant_id = $2",
            email,
            plant_id,
        )

        if not inventory_item:
            raise HTTPException(status_code=404, detail="Plant not found in inventory")

        await conn.execute(
            "DELETE FROM inventory WHERE email = $1 AND plant_id = $2", email, plant_id
        )

        await conn.execute("DELETE FROM plant WHERE plant_id = $1", plant_id)

    return {"message": "Plant removed from inventory"}


@app.patch("/users/{email}/money/add")
async def add_money(
    email: str,
    update: MoneyUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's money"
        )

    result = await conn.execute(
        'UPDATE "user" SET money = money + $1 WHERE email = $2', update.amount, email
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")

    new_balance = await conn.fetchval(
        'SELECT money FROM "user" WHERE email = $1', email
    )
    return {"message": "Money added successfully", "new_balance": new_balance}


@app.patch("/users/{email}/money/deduct")
async def deduct_money(
    email: str,
    update: MoneyUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's money"
        )

    current_money = await conn.fetchval(
        'SELECT money FROM "user" WHERE email = $1', email
    )

    if current_money is None:
        raise HTTPException(status_code=404, detail="User not found")

    if current_money < update.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    result = await conn.execute(
        'UPDATE "user" SET money = money - $1 WHERE email = $2', update.amount, email
    )

    new_balance = await conn.fetchval(
        'SELECT money FROM "user" WHERE email = $1', email
    )
    return {"message": "Money deducted successfully", "new_balance": new_balance}


@app.get("/users/{email}")
async def get_user(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot view another user's information"
        )

    user = await conn.fetchrow('SELECT * FROM "user" WHERE email = $1', email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(user)


@app.get("/users/{email}/inventory")
async def get_inventory(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot view another user's inventory"
        )

    seed_packets = await conn.fetch(
        """SELECT sp.* FROM seed_packet sp
           JOIN inventory i ON sp.seed_packet_id = i.seed_packet_id
           WHERE i.email = $1""",
        email,
    )

    plants = await conn.fetch(
        """SELECT p.* FROM plant p
           JOIN inventory i ON p.plant_id = i.plant_id
           WHERE i.email = $1""",
        email,
    )

    return {
        "seed_packets": [dict(sp) for sp in seed_packets],
        "plants": [dict(p) for p in plants],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
