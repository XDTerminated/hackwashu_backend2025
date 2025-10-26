# Pomo Patch API

Backend API for the Pomo Patch Pomodoro application. This FastAPI-based service manages user accounts, virtual plant gardens, and gamified productivity tracking.

## Overview

Pomo Patch is a gamified Pomodoro timer app where users earn money by completing focus sessions and grow virtual plants in their garden. The backend handles user authentication via Clerk, manages a PostgreSQL database, and provides RESTful endpoints for all game mechanics.

## Features

-   **User Management**: Create, update, and delete user accounts with Clerk authentication
-   **Plant System**: Purchase, grow, and sell plants with different rarities and species
-   **Economy System**: Earn and spend virtual currency on plants, water, fertilizer, and upgrades
-   **Growth Mechanics**: Water plants, apply fertilizer, and watch them grow through multiple stages
-   **Weather System**: Cycle through different weather conditions in your garden
-   **Leaderboard**: Track users by money earned

## Tech Stack

-   **FastAPI**: Modern web framework for building APIs
-   **PostgreSQL**: Database via asyncpg for async operations
-   **Clerk**: Authentication and user management
-   **JWT**: Token-based authentication
-   **Uvicorn**: ASGI server for running the application

## Prerequisites

-   Python 3.13+
-   PostgreSQL database
-   Clerk account for authentication

## Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd hackwashu_backend2025
```

2. Install dependencies:

```bash
pip install -e .
```

3. Create a `.env` file in the root directory with the following variables:

```
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
CLERK_SECRET_KEY=your_clerk_secret_key
CLERK_JWKS_URL=https://your-clerk-instance.clerk.accounts.dev/.well-known/jwks.json
```

## Database Setup

The application expects the following PostgreSQL tables:

**User Table:**

-   `email` (primary key)
-   `username` (unique)
-   `money` (float)
-   `plant_limit` (integer)
-   `weather` (integer)

**Plant Table:**

-   `plant_id` (primary key, auto-increment)
-   `plant_type` (string)
-   `plant_species` (string)
-   `size` (float)
-   `rarity` (integer)
-   `x` (float)
-   `y` (float)
-   `stage` (integer)
-   `growth_time_remaining` (integer, nullable)
-   `fertilizer_remaining` (integer, nullable)
-   `email` (foreign key to user)

## Running the Application

Start the development server:

```bash
python main.py
```

The API will be available at `http://localhost:8000`.

## API Endpoints

### User Endpoints

-   `GET /` - Welcome message
-   `POST /users/` - Create new user
-   `GET /users` - Get all users (leaderboard)
-   `GET /users/{email}` - Get user by email
-   `GET /users/by-username/{username}/{tag}` - Get user by username and tag
-   `PATCH /users/{email}/username` - Update username
-   `DELETE /users/{email}` - Delete user account
-   `PATCH /users/{email}/money` - Change user money
-   `POST /users/{email}/increase-plant-limit` - Upgrade plant capacity
-   `POST /users/{email}/cycle-weather` - Change garden weather

### Plant Endpoints

-   `POST /users/{email}/plants/` - Purchase and plant a new plant
-   `GET /users/{email}/plants` - Get all user plants
-   `GET /users/{email}/plants/{plant_id}` - Get specific plant
-   `PATCH /users/{email}/plants/{plant_id}/position` - Move plant position
-   `PATCH /users/{email}/plants/{plant_id}/apply-water` - Water a plant (stage 0)
-   `PATCH /users/{email}/plants/{plant_id}/apply-fertilizer` - Fertilize a plant (stage 1)
-   `PATCH /users/{email}/plants/{plant_id}/grow` - Update plant growth progress
-   `DELETE /users/{email}/plants/{plant_id}/sell` - Sell a plant for money

## Game Mechanics

### Plant Types & Rarity

Three plant types are available, each with three rarity levels:

-   **Fungi**: brown_mushroom (common), red_mushroom (rare), mario_mushroom (legendary)
-   **Rose**: red_rose (common), pink_rose/white_rose (rare), withered_rose (legendary)
-   **Berry**: blueberry (common), strawberry (rare), ancient_fruit (legendary)

Rarity probabilities:

-   Common: 79%
-   Rare: 20%
-   Legendary: 1%

### Growth Stages

-   **Stage 0**: Seed (needs water to start growing, 30 minutes)
-   **Stage 1**: Sprout (needs fertilizer, 60-360 minutes based on rarity)
-   **Stage 2**: Fully grown (ready to sell)

### Economy

-   Plant cost: 100 coins
-   Water cost: 25 coins
-   Fertilizer cost: 25 coins
-   Starting money: 250 coins
-   Plant limit upgrade: 1000 coins base (increases by 1.1x each time)

### Sell Values

| Rarity    | Stage 1 | Stage 2 |
| --------- | ------- | ------- |
| Common    | 50      | 100     |
| Rare      | 100     | 200     |
| Legendary | 250     | 500     |

## Authentication

All user-specific endpoints require a Bearer token in the Authorization header:

```
Authorization: Bearer <clerk_jwt_token>
```

The token is verified using Clerk's JWKS endpoint and must contain the user's email.

## CORS Configuration

The API allows requests from:

-   `http://localhost:5173`
-   `http://localhost:1420`
-   `http://127.0.0.1:5173`
-   `http://127.0.0.1:1420`

Modify the `allow_origins` list in `main.py` to add additional origins.

## Development

The application uses:

-   Async database connections with connection pooling
-   JWT validation via PyJWKClient
-   Pydantic models for request validation
-   Transaction management for atomic operations

## License

This project was created for HackWashU 2025.
