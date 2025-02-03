from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from Model.items import Item  
from database.database import SessionLocal, engine

# Criar a tabela no banco (caso não tenha sido criada via Alembic)
Item.metadata.create_all(bind=engine)

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/items/")
def create_item(name: str, description: str, db: Session = Depends(get_db)):
    new_item = Item(name=name, description=description)
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item

@app.get("/items/")
def read_items(db: Session = Depends(get_db)):
    return db.query(Item).all()
