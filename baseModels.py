from pydantic import BaseModel

class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    user_id: str

class SfDifficulty(BaseModel):
    level: str

class Game(BaseModel):
    game_id: str
    user_id: str
    fen: str
    move: list
    result: str
    difficulty: str
    time: int
    moveNumber: int