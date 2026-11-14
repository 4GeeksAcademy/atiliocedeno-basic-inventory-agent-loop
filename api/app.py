from fastapi import FastAPI

app = FastAPI()


@app.get("/inventory")
def list_inventory():
    return [ 