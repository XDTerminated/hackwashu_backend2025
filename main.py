from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
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


class UsernameUpdate(BaseModel):
    new_username: str


class MoneyChange(BaseModel):
    amount: float

class WaterChange(BaseModel):
    amount: int

class FertilizerChange(BaseModel):
    amount: int

class PlantCreate(BaseModel):
    rarity: int
    x: float
    y: float


class PlantPosition(BaseModel):
    x: float
    y: float


class GrowthTimeUpdate(BaseModel):
    time: int


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
            'INSERT INTO "user" (username, email, money, water, fertilizer) VALUES ($1, $2, $3, $4, $5)',
            user.username,
            user.email,
            250.0,
            0,
            0,
        )
        return {
            "message": "User created successfully",
            "email": user.email,
            "username": user.username,
            "money": 250.0,
            "water": 0,
            "fertilizer": 0,
        }
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=400, detail="User with this email already exists"
        )


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
        await conn.execute("DELETE FROM plant WHERE email = $1", email)
        result = await conn.execute('DELETE FROM "user" WHERE email = $1', email)

        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted successfully"}


@app.patch("/users/{email}/money")
async def change_money(
    email: str,
    update: MoneyChange,
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
    return {"message": "Money updated successfully", "new_balance": new_balance}

@app.patch("/users/{email}/water")
async def change_water(
    email: str,
    update: WaterChange,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's water"
        )

    result = await conn.execute(
        'UPDATE "user" SET water = water + $1 WHERE email = $2', update.amount, email
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")

    new_water = await conn.fetchval(
        'SELECT water FROM "user" WHERE email = $1', email
    )
    return {"message": "Water updated successfully", "new_water": new_water}

@app.patch("/users/{email}/fertilizer")
async def change_fertilizer(
    email: str,
    update: FertilizerChange,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's fertilizer"
        )

    result = await conn.execute(
        'UPDATE "user" SET fertilizer = fertilizer + $1 WHERE email = $2', update.amount, email
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")

    new_fertilizer = await conn.fetchval(
        'SELECT fertilizer FROM "user" WHERE email = $1', email
    )
    return {"message": "Fertilizer updated successfully", "new_fertilizer": new_fertilizer}


@app.post("/users/{email}/plants/", status_code=201)
async def create_plant(
    email: str,
    plant: PlantCreate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    user = await conn.fetchrow('SELECT * FROM "user" WHERE email = $1', email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if plant.rarity not in [0, 1, 2]:
        raise HTTPException(
            status_code=400, detail="Rarity must be 0, 1, or 2"
        )

    plant_id = await conn.fetchval(
        """INSERT INTO plant (plant_type, size, rarity, x, y, stage, growth_time_remaining, email)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING plant_id""",
        "default",
        0.0,
        plant.rarity,
        plant.x,
        plant.y,
        0,
        None,
        email,
    )

    return {"message": "Plant created successfully", "plant_id": plant_id}


@app.patch("/users/{email}/plants/{plant_id}/position")
async def move_plant(
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

    result = await conn.execute(
        "UPDATE plant SET x = $1, y = $2 WHERE plant_id = $3 AND email = $4",
        position.x,
        position.y,
        plant_id,
        email,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Plant not found")

    return {"message": "Plant moved successfully", "x": position.x, "y": position.y}


@app.patch("/users/{email}/plants/{plant_id}/start-growing")
async def start_growing_plant(
    email: str,
    plant_id: int,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    plant = await conn.fetchrow(
        "SELECT stage, rarity FROM plant WHERE plant_id = $1 AND email = $2",
        plant_id,
        email,
    )

    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    stage = plant["stage"]
    rarity = plant["rarity"]

    if stage == 0:
        growth_time = 30
    elif stage == 1:
        growth_times = {0: 60, 1: 120, 2: 360}
        growth_time = growth_times[rarity]
    else:
        raise HTTPException(
            status_code=400, detail="Plant is already fully grown (stage 2)"
        )

    result = await conn.execute(
        "UPDATE plant SET growth_time_remaining = $1 WHERE plant_id = $2 AND email = $3",
        growth_time,
        plant_id,
        email,
    )

    return {
        "message": "Plant started growing",
        "growth_time_remaining": growth_time,
    }


@app.patch("/users/{email}/plants/{plant_id}/grow")
async def grow_plant_by_time(
    email: str,
    plant_id: int,
    update: GrowthTimeUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    plant = await conn.fetchrow(
        "SELECT growth_time_remaining FROM plant WHERE plant_id = $1 AND email = $2",
        plant_id,
        email,
    )

    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    if plant["growth_time_remaining"] is None:
        raise HTTPException(
            status_code=400, detail="Plant is not currently growing"
        )

    new_time = max(0, plant["growth_time_remaining"] - update.time)

    await conn.execute(
        "UPDATE plant SET growth_time_remaining = $1 WHERE plant_id = $2 AND email = $3",
        new_time,
        plant_id,
        email,
    )

    return {
        "message": "Plant growth updated",
        "growth_time_remaining": new_time,
    }


@app.patch("/users/{email}/plants/{plant_id}/advance-stage")
async def advance_plant_stage(
    email: str,
    plant_id: int,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    plant = await conn.fetchrow(
        "SELECT stage FROM plant WHERE plant_id = $1 AND email = $2",
        plant_id,
        email,
    )

    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    current_stage = plant["stage"]

    if current_stage >= 2:
        raise HTTPException(
            status_code=400, detail="Plant is already at maximum stage"
        )

    new_stage = current_stage + 1

    await conn.execute(
        "UPDATE plant SET stage = $1, growth_time_remaining = NULL WHERE plant_id = $2 AND email = $3",
        new_stage,
        plant_id,
        email,
    )

    return {
        "message": "Plant advanced to next stage",
        "new_stage": new_stage,
    }


@app.delete("/users/{email}/plants/{plant_id}/sell")
async def sell_plant(
    email: str,
    plant_id: int,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plants"
        )

    async with conn.transaction():
        plant = await conn.fetchrow(
            "SELECT stage, rarity FROM plant WHERE plant_id = $1 AND email = $2",
            plant_id,
            email,
        )

        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")

        stage = plant["stage"]
        rarity = plant["rarity"]

        if stage == 0:
            money_earned = 0
        elif stage == 1:
            money_values = {0: 50, 1: 100, 2: 250}
            money_earned = money_values[rarity]
        else:
            money_values = {0: 100, 1: 200, 2: 500}
            money_earned = money_values[rarity]

        await conn.execute(
            "DELETE FROM plant WHERE plant_id = $1 AND email = $2",
            plant_id,
            email,
        )

        if money_earned > 0:
            await conn.execute(
                'UPDATE "user" SET money = money + $1 WHERE email = $2',
                money_earned,
                email,
            )

        new_balance = await conn.fetchval(
            'SELECT money FROM "user" WHERE email = $1', email
        )

    return {
        "message": "Plant sold successfully",
        "money_earned": money_earned,
        "new_balance": new_balance,
    }


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


@app.get("/users/{email}/plants")
async def get_user_plants(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot view another user's plants"
        )

    plants = await conn.fetch(
        "SELECT * FROM plant WHERE email = $1",
        email,
    )

    return {"plants": [dict(p) for p in plants]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)