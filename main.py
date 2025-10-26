from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import asyncpg
import os
from dotenv import load_dotenv
import jwt
from jwt import PyJWKClient
import random

load_dotenv()

app = FastAPI(title="Pomo Patch API")

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

WATER_COST = 25
FERTILIZER_COST = 25
PLANT_COST = 100
INITIAL_USER_MONEY = 250.0
INITIAL_PLANT_LIMIT = 25
INITIAL_WEATHER = 0
PLANT_LIMIT_BASE_COST = 1000
PLANT_LIMIT_COST_MULTIPLIER = 1.1
PLANT_LIMIT_INCREASE = 25
STAGE_0_GROWTH_TIME = 30

PLANT_SPECIES = {
    "fungi": {
        0: ["brown_mushroom"],
        1: ["red_mushroom"],
        2: ["mario_mushroom"]
    },
    "rose": {
        0: ["red_rose"],
        1: ["pink_rose", "white_rose"],
        2: ["withered_rose"]
    },
    "berry": {
        0: ["blueberry"],
        1: ["strawberry"],
        2: ["ancient_fruit"]
    },
}

RARITY_PROBABILITIES = {
    0: 0.79,  # Rare
    1: 0.20,  # Epic (0.79 + 0.20 = 0.99)
    2: 0.01   # Legendary (remaining)
}

STAGE_1_GROWTH_TIMES = {0: 60, 1: 120, 2: 360}

STAGE_1_SELL_VALUES = {0: 50, 1: 100, 2: 250}
STAGE_2_SELL_VALUES = {0: 100, 1: 200, 2: 500}


def generate_random_size():
    """Generate a random size between 0 and 1 using normal distribution."""
    size = random.gauss(0.5, 0.2)
    return max(0.0, min(1.0, size))


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
    email: EmailStr


class UsernameUpdate(BaseModel):
    new_username: str


class MoneyChange(BaseModel):
    amount: float


class PlantCreate(BaseModel):
    plant_type: str
    x: float
    y: float


class PlantPosition(BaseModel):
    x: float
    y: float


class GrowthTimeUpdate(BaseModel):
    time: int


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Pomo Patch API"}


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

    existing = await conn.fetchval('SELECT 1 FROM "user" WHERE email = $1', user.email)
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    base_username = user.email.split('@')[0]

    for i in range(10000):
        candidate = f"{base_username}#{i:04d}"
        try:
            await conn.execute(
                'INSERT INTO "user" (username, email, money, plant_limit, weather) VALUES ($1, $2, $3, $4, $5)',
                candidate,
                user.email,
                INITIAL_USER_MONEY,
                INITIAL_PLANT_LIMIT,
                INITIAL_WEATHER,
            )

            return {
                "message": "User created successfully",
                "email": user.email,
                "username": candidate,
                "money": INITIAL_USER_MONEY,
                "plant_limit": INITIAL_PLANT_LIMIT,
                "weather": INITIAL_WEATHER,
            }
        except asyncpg.UniqueViolationError:
            continue

    raise HTTPException(status_code=500, detail="Unable to generate a unique username")


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


@app.post("/users/{email}/increase-plant-limit")
async def increase_plant_limit(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's plant limit"
        )

    async with conn.transaction():
        user = await conn.fetchrow('SELECT money, plant_limit FROM "user" WHERE email = $1', email)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        num_upgrades = (user["plant_limit"] - INITIAL_PLANT_LIMIT) // PLANT_LIMIT_INCREASE
        cost = round(int(PLANT_LIMIT_BASE_COST * (PLANT_LIMIT_COST_MULTIPLIER ** num_upgrades)), -2)
        
        if user["money"] < cost:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient money to increase plant limit. Need {cost}, have {user['money']}"
            )
        
        await conn.execute(
            'UPDATE "user" SET money = money - $1, plant_limit = plant_limit + $2 WHERE email = $3',
            cost,
            PLANT_LIMIT_INCREASE,
            email
        )
        
        new_money = await conn.fetchval('SELECT money FROM "user" WHERE email = $1', email)
        new_plant_limit = await conn.fetchval('SELECT plant_limit FROM "user" WHERE email = $1', email)
        
        next_cost = round(int(PLANT_LIMIT_BASE_COST * (PLANT_LIMIT_COST_MULTIPLIER ** (num_upgrades + 1))), -2)

    return {
        "message": "Plant limit increased successfully",
        "cost_paid": cost,
        "new_money": new_money,
        "new_plant_limit": new_plant_limit,
        "next_upgrade_cost": next_cost
    }


@app.post("/users/{email}/cycle-weather")
async def cycle_weather(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
    auth_email: str = Depends(verify_clerk_token),
):
    if email != auth_email:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's weather"
        )

    user = await conn.fetchrow('SELECT weather FROM "user" WHERE email = $1', email)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_weather = user["weather"]
    new_weather = (current_weather + 1) % 3
    
    await conn.execute(
        'UPDATE "user" SET weather = $1 WHERE email = $2',
        new_weather,
        email
    )
    
    return {
        "message": "Weather cycled successfully",
        "previous_weather": current_weather,
        "new_weather": new_weather
    }


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

    async with conn.transaction():
        user = await conn.fetchrow('SELECT money, plant_limit FROM "user" WHERE email = $1', email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        current_plant_count = await conn.fetchval(
            "SELECT COUNT(*) FROM plant WHERE email = $1",
            email
        )
        
        if current_plant_count >= user["plant_limit"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Plant limit reached. Current: {current_plant_count}/{user['plant_limit']}"
            )

        if user["money"] < PLANT_COST:
            raise HTTPException(
                status_code=400, detail=f"Insufficient money. Need {PLANT_COST} to create a plant"
            )

        if plant.plant_type not in PLANT_SPECIES:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid plant_type. Must be one of: {', '.join(PLANT_SPECIES.keys())}"
            )

        rand = random.random()
        if rand < RARITY_PROBABILITIES[0]:
            rarity = 0
        elif rand < RARITY_PROBABILITIES[0] + RARITY_PROBABILITIES[1]:
            rarity = 1
        else:
            rarity = 2

        species_list = PLANT_SPECIES[plant.plant_type][rarity]
        plant_species = random.choice(species_list)
        
        # Generate random size using normal distribution
        plant_size = generate_random_size()

        await conn.execute(
            'UPDATE "user" SET money = money - $1 WHERE email = $2',
            PLANT_COST,
            email
        )

        plant_id = await conn.fetchval(
            """INSERT INTO plant (plant_type, plant_species, size, rarity, x, y, stage, growth_time_remaining, email)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING plant_id""",
            plant.plant_type,
            plant_species,
            plant_size,
            rarity,
            plant.x,
            plant.y,
            0,
            None,
            email,
        )

        new_balance = await conn.fetchval('SELECT money FROM "user" WHERE email = $1', email)

    return {
        "message": "Plant created successfully",
        "plant_id": plant_id,
        "plant_type": plant.plant_type,
        "plant_species": plant_species,
        "size": plant_size,
        "rarity": rarity,
        "money_spent": PLANT_COST,
        "new_balance": new_balance
    }


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


@app.patch("/users/{email}/plants/{plant_id}/apply-water")
async def apply_water(
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
            "SELECT stage, growth_time_remaining FROM plant WHERE plant_id = $1 AND email = $2",
            plant_id,
            email,
        )

        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")

        stage = plant["stage"]
        growth_time_remaining = plant.get("growth_time_remaining")

        if stage != 0:
            raise HTTPException(
                status_code=400, detail="Can only water plants at stage 0"
            )
        
        if growth_time_remaining is not None:
            raise HTTPException(
                status_code=400, detail="Plant is already growing and doesn't need water"
            )

        user = await conn.fetchrow('SELECT money FROM "user" WHERE email = $1', email)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user["money"] < WATER_COST:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient money. Need {WATER_COST}, have {user['money']}"
            )
        
        await conn.execute(
            'UPDATE "user" SET money = money - $1 WHERE email = $2',
            WATER_COST,
            email
        )
        
        await conn.execute(
            "UPDATE plant SET growth_time_remaining = $1 WHERE plant_id = $2 AND email = $3",
            STAGE_0_GROWTH_TIME,
            plant_id,
            email,
        )
        
        new_money = await conn.fetchval('SELECT money FROM "user" WHERE email = $1', email)
        
        return {
            "message": "Water applied, plant started growing",
            "cost": WATER_COST,
            "new_money": new_money,
            "growth_time_remaining": STAGE_0_GROWTH_TIME
        }


@app.patch("/users/{email}/plants/{plant_id}/apply-fertilizer")
async def apply_fertilizer(
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
            "SELECT stage, fertilizer_remaining, rarity, growth_time_remaining FROM plant WHERE plant_id = $1 AND email = $2",
            plant_id,
            email,
        )

        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")

        stage = plant["stage"]
        fertilizer_remaining = plant["fertilizer_remaining"]
        growth_time_remaining = plant.get("growth_time_remaining")

        if stage != 1:
            raise HTTPException(
                status_code=400, detail="Can only fertilize plants at stage 1"
            )

        if fertilizer_remaining is None or fertilizer_remaining == 0:
            raise HTTPException(
                status_code=400, detail="Plant doesn't need fertilizer"
            )
        
        if growth_time_remaining is not None:
            raise HTTPException(
                status_code=400, detail="Plant is already growing and doesn't need fertilizer"
            )

        user = await conn.fetchrow('SELECT money FROM "user" WHERE email = $1', email)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user["money"] < FERTILIZER_COST:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient money. Need {FERTILIZER_COST}, have {user['money']}"
            )
        
        await conn.execute(
            'UPDATE "user" SET money = money - $1 WHERE email = $2',
            FERTILIZER_COST,
            email
        )
        
        new_fertilizer_remaining = fertilizer_remaining - 1
        
        if new_fertilizer_remaining == 0:
            growth_time = STAGE_1_GROWTH_TIMES[plant["rarity"]]
            
            await conn.execute(
                "UPDATE plant SET fertilizer_remaining = NULL, growth_time_remaining = $1 WHERE plant_id = $2 AND email = $3",
                growth_time,
                plant_id,
                email
            )
            
            new_money = await conn.fetchval('SELECT money FROM "user" WHERE email = $1', email)
            
            return {
                "message": "Fertilizer applied, plant started growing",
                "cost": FERTILIZER_COST,
                "new_money": new_money,
                "fertilizer_remaining": None,
                "growth_time_remaining": growth_time
            }
        else:
            await conn.execute(
                "UPDATE plant SET fertilizer_remaining = $1 WHERE plant_id = $2 AND email = $3",
                new_fertilizer_remaining,
                plant_id,
                email
            )
            
            new_money = await conn.fetchval('SELECT money FROM "user" WHERE email = $1', email)
            
            return {
                "message": "Fertilizer applied",
                "cost": FERTILIZER_COST,
                "new_money": new_money,
                "fertilizer_remaining": new_fertilizer_remaining,
                "growth_time_remaining": None
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

    async with conn.transaction():
        plant = await conn.fetchrow(
            "SELECT growth_time_remaining, stage, rarity FROM plant WHERE plant_id = $1 AND email = $2",
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

        if new_time == 0:
            current_stage = plant["stage"]

            if current_stage >= 2:
                raise HTTPException(
                    status_code=400, detail="Plant is already at maximum stage"
                )

            new_stage = current_stage + 1

            # If advancing to stage 1, initialize fertilizer_remaining based on rarity
            if new_stage == 1:
                rarity = plant.get("rarity", 0)
                # Map rarity to fertilizer counts: 0 -> 1, 1 -> 2, 2 -> 5
                fertilizer_map = {0: 1, 1: 2, 2: 5}
                fertilizer_init = fertilizer_map.get(rarity, 1)

                await conn.execute(
                    "UPDATE plant SET stage = $1, growth_time_remaining = NULL, fertilizer_remaining = $2 WHERE plant_id = $3 AND email = $4",
                    new_stage,
                    fertilizer_init,
                    plant_id,
                    email,
                )
            else:
                # Advancing to stage 2 or higher: clear fertilizer_remaining
                await conn.execute(
                    "UPDATE plant SET stage = $1, growth_time_remaining = NULL, fertilizer_remaining = NULL WHERE plant_id = $2 AND email = $3",
                    new_stage,
                    plant_id,
                    email,
                )

            return {
                "message": "Plant growth completed and advanced to next stage",
                "growth_time_remaining": None,
                "new_stage": new_stage,
                "stage_advanced": True,
            }
        else:
            await conn.execute(
                "UPDATE plant SET growth_time_remaining = $1 WHERE plant_id = $2 AND email = $3",
                new_time,
                plant_id,
                email,
            )
            
            return {
                "message": "Plant growth updated",
                "growth_time_remaining": new_time,
                "stage_advanced": False
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
            money_earned = STAGE_1_SELL_VALUES[rarity]
        else:
            money_earned = STAGE_2_SELL_VALUES[rarity]

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


@app.get("/users")
async def get_users(
    conn: asyncpg.Connection = Depends(get_db),
):
    users = await conn.fetch('SELECT * FROM "user" ORDER BY money DESC')
    return {"users": [dict(u) for u in users]}


@app.get("/users/{email}")
async def get_user(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
):
    user = await conn.fetchrow('SELECT * FROM "user" WHERE email = $1', email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(user)


@app.get("/users/by-username/{username}/{tag}")
async def get_user_from_username(
    username: str,
    tag: str,
    conn: asyncpg.Connection = Depends(get_db),
):
    full_username = f"{username}#{tag}"
    user = await conn.fetchrow('SELECT * FROM "user" WHERE username = $1', full_username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(user)


@app.get("/users/{email}/plants/{plant_id}")
async def get_user_plant(
    email: str,
    plant_id: int,
    conn: asyncpg.Connection = Depends(get_db),
):
    plant = await conn.fetchrow(
        "SELECT * FROM plant WHERE plant_id = $1 AND email = $2",
        plant_id,
        email,
    )

    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    return dict(plant)


@app.get("/users/{email}/plants")
async def get_user_plants(
    email: str,
    conn: asyncpg.Connection = Depends(get_db),
):
    plants = await conn.fetch(
        "SELECT * FROM plant WHERE email = $1",
        email,
    )

    return {"plants": [dict(p) for p in plants]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)