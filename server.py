import uvicorn
from dotenv import load_dotenv


load_dotenv()


if __name__ == "__main__":
    uvicorn.run("iceberg_search.api.app:app", host="0.0.0.0", port=8000, reload=True)
