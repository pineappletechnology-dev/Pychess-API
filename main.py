from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.models import APIKey
from fastapi.openapi.utils import get_openapi
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import desc
from sqlalchemy.orm import Session
from database.database import SessionLocal, engine
from stockfish import Stockfish
from passlib.hash import bcrypt
from database.database import get_db 
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from pydantic import BaseModel

from Model.users import User
from Model.games import Game
from Model.moves import Move

import jwt
import math
import time
import math
import os
import smtplib

# Importação dos arquivos
import gameMethods
import dbMethods
import baseModels

app = FastAPI(
    title="Minha API",
    description="API com autenticação JWT",
    version="1.0",
    openapi_tags=[{"name": "DB", "description": "Rotas que acessam o banco de dados"}],
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

origins = [
    "http://localhost:3000",
]
# Adiciona o middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            # Ou use ["*"] para tudo (dev)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Minha API",
        version="1.0",
        description="API com autenticação JWT",
        routes=app.routes,
    )
    openapi_schema["components"] = {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT"
            }
        }
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

load_dotenv()

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

print("STOCKFISH_PATH:", STOCKFISH_PATH)

security = HTTPBearer()

# Inicializa o motor Stockfish
stockfish = Stockfish(STOCKFISH_PATH)
stockfish.set_skill_level(10)  # Ajuste o nível de habilidade (0-20)
stockfish.set_depth(15)  # Profundidade de busca

# Variável para armazenar o histórico do jogo
game_moves = []
saved_games = {}

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security), db: Session = Depends(get_db)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        user_id = payload.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = dbMethods.getUserByFilter({"id": user_id}, db)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/set_difficulty/", tags=['GAME'])
def set_difficulty(payload: baseModels.SfDifficulty, db: Session = Depends(get_db)):
    """Define o nível de dificuldade do Stockfish"""

    difficulty = gameMethods.setStockfishDifficultyLevel(payload.level)

    if not difficulty:
        raise HTTPException(status_code=400, detail={"error": "Nível inválido! Escolha entre: muito_baixa, baixa, media, dificil, extremo."})

    return {"message": "Nível de dificuldade definido com sucesso!", "difficulty": difficulty}

@app.post("/start_game/", tags=['GAME'])
def start_game(payload: baseModels.UserRegister, db: Session = Depends(get_db)):
    """ Inicia um novo jogo de xadrez. """
    
    # Verifica se há algum jogo em andamento
    existing_game = gameMethods.verifyExistingGame(db)
    
    if existing_game:
        raise HTTPException(status_code=400, detail="Já existe um jogo em andamento!")

    new_game = gameMethods.startNewGame(payload.user_id, db)

    return {"message": "Jogo iniciado!", "game_id": new_game.id, "board": stockfish.get_board_visual()}

@app.post("/load_game/", tags=['GAME'])
def load_game(payload: baseModels.Game, db: Session = Depends(get_db)):
    gameMethods.loadGame(payload.game_id, db)

    return {
        "message": f"Jogo {payload.game_id} carregado!",
        "board": stockfish.get_board_visual().split("\n")  # Divide em linhas para exibição
    }

@app.get("/game_state_per_moviment/", tags=['GAME'])
def get_game_state_per_moviment(payload: baseModels.Game, db: Session = Depends(get_db)):

    gameMethods.getGameState(payload.game_id, payload.move_number, db)

    return {
        "message": f"Jogo {payload.game_id} após {payload.move_number} jogadas.",
        "board": stockfish.get_board_visual().split("\n")  # Divide para exibição
    }


@app.get("/game_board/", tags=['GAME'])
def get_game_board(db: Session = Depends(get_db)):
    board_visual = gameMethods.getGameBoard(db)

    return {"board": board_visual}


@app.post("/play_game/", tags=['GAME'])
def play_game(payload: baseModels.Game, db: Session = Depends(get_db)):
    """ O usuário joga, e o Stockfish responde com a melhor jogada, verificando capturas. """
    playing = gameMethods.playGame(payload.move, db)
    
    return {
        "message": "Movimentos realizados!",
        "player_move": payload.move,
        "player_capture": playing.captured_piece_position,
        "stockfish_move": playing.best_move,
        "stockfish_capture": playing.captured_piece_position_stockfish,
        "board": stockfish.get_board_visual()
    }

@app.get("/evaluate_position/", tags=['GAME'])
def evaluate_position(db: Session = Depends(get_db)):
    evaluation = gameMethods.evaulatePosition(db)

    return {
        "evaluation": evaluation.centipawns,
        "best_depth": evaluation.best_depth,
        "win_probability_white": round(evaluation.win_probability, 2),
        "win_probability_black": round(100 - evaluation.win_probability, 2),
        "board": stockfish.get_board_visual()
    }

@app.post("/rating/", tags=['GAME'])
def rating(payload: baseModels.UserRegister, db: Session = Depends(get_db)):
    rating = gameMethods.getRating(payload.user_id, db)

    return {
        "message": "Avaliação concluída!",
        "final_rating": rating.final_rating,
        "rating_updated": rating.userRating, 
        "moves_analyzed": len(rating.game_moves)
    }

@app.post("/analyze_move/",tags=['GAME'])
def analyze_move(payload: baseModels.Game,  db: Session = Depends(get_db)):
    analyzed = gameMethods.analyzeMove(payload.move, db)

    return {
        "move": payload.move,
        "best_move": analyzed.best_move,
        "evaluation_before": analyzed.eval_before_score,
        "evaluation_after": analyzed.eval_after_score,
        "evaluation_best_move": analyzed.eval_best_score,
        "classification": analyzed.classification,
        "board": stockfish.get_board_visual()
    }

@app.get("/game_history/",tags=['GAME'])
def game_history(db: Session = Depends(get_db)):
    game_moves = gameMethods.getGameHistory(db)
    return {"moves": game_moves}

@app.post("/evaluate_progress/", tags=['GAME'])
def evaluate_progress():
    progress = gameMethods.evaluateProgress()

    return {
        "message": "Comparação realizada!",
        "progress": progress
    }

# ROTAS A SEREM USADAS AO PENSAR EM INTEGRAR COM O ROBO
@app.get("/get_position/{square}", tags=['ROBOT'])
def get_position(square: str):

    position = gameMethods.getPosition(square)

    return {"square": square, "x": position[0], "y": position[1]}

# Rotas de conexão DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/register/",tags=['DB'])
def create_user(payload: baseModels.UserRegister, db: Session = Depends(get_db)):
    new_user = dbMethods.createUser(payload.username, payload.password, payload.email, db)

    return {
        "message": "User created successfully", 
        "id": new_user.id
    }

@app.get("/get-users/", tags=['DB'])
def get_users(db: Session = Depends(get_db)):
    users = dbMethods.getUsers(db)

    return [
        {
            "username": user.username,
            "rating": user.rating
        }
        for user in users
    ]

@app.post("/login/", tags=['DB'])
def login(payload: baseModels.UserRegister, db: Session = Depends(get_db)):
    token = dbMethods.login(payload.username, payload.password, SECRET_KEY, ALGORITHM, db)
    
    return {"message": "Login successful", "token": token}

@app.get("/user-session/", tags=['DB'])
def get_user_info(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "wins": user.wins,
        "losses": user.losses,
        "total_games": user.total_games
    }

@app.post("/forgot-password/", tags=['DB'])
def forgot_password(payload: baseModels.UserRegister, db: Session = Depends(get_db)):
    # """ Verifica se o e-mail existe e envia um link de recuperação """
    # user = db.query(User).filter(User.email == email).first()
    
    # if not user:
    #     raise HTTPException(status_code=404, detail="E-mail não encontrado.")
    
    # # Gerar token de redefinição de senha
    # reset_token = create_reset_token(email)
    
    # # Enviar e-mail com link
    # send_reset_email(email, reset_token)

    dbMethods.forgotPassword(payload.email, db)
    
    return {"message": "E-mail de redefinição de senha enviado!"}
