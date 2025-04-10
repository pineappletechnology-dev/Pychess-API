from pydantic import BaseModel

class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    user_id: str

class sfDifficulty(BaseModel):
    level: str

class game(BaseModel):
    game_id: str
    user_id: str
    fen: str
    moves: list
    result: str
    difficulty: str
    time: int