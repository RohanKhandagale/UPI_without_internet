import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=os.getenv("UPI_NETWORK_HOST", "127.0.0.1"),
                port=int(os.getenv("UPI_NETWORK_PORT", "8080")), reload=False)
