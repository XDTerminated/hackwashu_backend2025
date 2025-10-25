from fastapi import FastAPI
from dotenv import load_dotenv
import psycopg
import os

app = FastAPI()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
