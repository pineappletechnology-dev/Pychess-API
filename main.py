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

def create_reset_token(email: str):
    """ Gera um token JWT para redefinição de senha """
    expire = datetime.utcnow() + timedelta(minutes=30)
    data = {"sub": email, "exp": expire}
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def send_reset_email(email: str, token: str):
    """ Envia o e-mail com o link para redefinir senha """
    reset_link = f"http://localhost:8000/reset-password?token={token}"
    
    msg = MIMEMultipart()
    msg["From"] = os.getenv("SMTP_EMAIL")
    msg["To"] = email
    msg["Subject"] = "Redefinição de Senha"
    
    body = f"""
    <p>Olá,</p>
    <p>Você solicitou a redefinição de senha. Clique no link abaixo para redefinir sua senha:</p>
    <p><a href="{reset_link}">Redefinir Senha</a></p>
    <p>Este link expira em {30} minutos.</p>
    """
    
    msg.attach(MIMEText(body, "html"))

    try:
        server = smtplib.SMTP(os.getenv("SMTP_SERVER"), os.getenv("SMTP_PORT"))
        server.starttls()
        server.login(os.getenv("SMTP_EMAIL"), os.getenv("SMTP_PASSWORD"))
        server.sendmail(os.getenv("SMTP_EMAIL"), email, msg.as_string())
        server.quit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enviar e-mail: {str(e)}")

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
    """ Avalia a posição do tabuleiro por 5 segundos, aumentando a profundidade da análise a cada segundo. """
    game = db.query(Game).filter(Game.player_win == 0).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings
    stockfish.set_position(game_moves)  # Garante que estamos avaliando o estado atual

    best_evaluation = None
    best_depth = 0

    for depth in range(8, 8 + 5):  # Começa na profundidade 8 e vai até 12
        stockfish.set_depth(depth)
        evaluation = stockfish.get_evaluation()
        
        # Atualiza a melhor avaliação encontrada
        if best_evaluation is None or abs(evaluation["value"]) > abs(best_evaluation["value"]):
            best_evaluation = evaluation
            best_depth = depth

        time.sleep(1) 

    # Verifica se houve xeque-mate
    if best_evaluation["type"] == "mate":
        if best_evaluation["value"] > 0:
            return {"winner": "Brancas", "win_probability": 100, "lose_probability": 0}
        else:
            return {"winner": "Pretas", "win_probability": 100, "lose_probability": 0}

    # Convertendo a vantagem do Stockfish para probabilidade de vitória
    centipawns = best_evaluation["value"]
    win_probability = 1 / (1 + math.exp(-0.004 * centipawns)) * 100  # Fórmula de conversão

    return {
        "evaluation": centipawns,
        "best_depth": best_depth,
        "win_probability_white": round(win_probability, 2),
        "win_probability_black": round(100 - win_probability, 2),
        "board": stockfish.get_board_visual()
    }

@app.post("/rating/", tags=['GAME'])
def rating(user_id: int, db: Session = Depends(get_db)):
    """Avalia o jogo completo armazenado em game_moves e atualiza o rating do jogador no banco de dados."""

    global stockfish

    game = db.query(Game).filter(Game.player_win == 0).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings

    # Verifica se há jogadas para avaliar
    if not game_moves:
        raise HTTPException(status_code=400, detail="Nenhuma jogada registrada para avaliação.")

    # Busca o usuário e seu rating atual
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado!")

    base_rating = user.rating  # Rating atual do jogador
    rating = base_rating  # Inicializa o rating com o valor do banco

    stockfish.set_position([])  # Reseta o Stockfish para o início da partida

    for i, move in enumerate(game_moves):
        if not stockfish.is_move_correct(move):
            raise HTTPException(status_code=400, detail=f"Movimento inválido detectado: {move}")

        stockfish.set_position(game_moves[:i + 1])  # Atualiza posição até a jogada atual

        best_move = stockfish.get_best_move()  # Melhor jogada segundo Stockfish
        evaluation_before = stockfish.get_evaluation()  # Avaliação antes do movimento
        stockfish.make_moves_from_current_position([move])  # Aplica o movimento no Stockfish
        evaluation_after = stockfish.get_evaluation()  # Avaliação depois do movimento
        
        eval_diff = evaluation_before["value"] - evaluation_after["value"]

        if best_move == move:
            rating += 50  # Jogada perfeita
        elif eval_diff > 200:
            rating -= 50  # Erro grave (Blunder)
        elif eval_diff > 100:
            rating -= 20  # Jogada imprecisa
        elif eval_diff > 30:
            rating -= 5   # Pequeno erro
        else:
            rating += 5   # Jogada sólida

    # Garante que o rating final não fique negativo
    final_rating = max(0, rating)

    # Calcula a diferença entre o rating final e o atual do jogador
    rating_diff = final_rating - base_rating

    # Atualiza o rating no banco de dados conforme a diferença
    if rating_diff >= 200:
        user.rating += 100
    elif rating_diff >= 100:
        user.rating += 70
    elif rating_diff >= 20:
        user.rating += 50
    elif rating_diff > 0:
        user.rating += 20

    db.commit()

    return {
        "message": "Avaliação concluída!",
        "final_rating": final_rating,
        "rating_updated": user.rating, 
        "moves_analyzed": len(game_moves)
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
    """ Retorna o histórico de jogadas do jogo atual. """
    game = db.query(Game).filter(Game.player_win == 0).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings

    return {"moves": game_moves}

@app.post("/evaluate_progress/", tags=['GAME'])
def evaluate_progress():
    """Compara as três últimas partidas e verifica a evolução do jogador."""
    global game_moves, game_history, stockfish

    if not game_moves:
        raise HTTPException(status_code=400, detail="Nenhuma partida registrada para avaliação.")

    # Adiciona a última partida ao histórico
    if len(game_history) >= 3:
        game_history.pop(0)  # Remove a mais antiga para manter apenas 3 partidas

    game_history.append(list(game_moves))  # Salva o jogo atual

    if len(game_history) < 3:
        return {"message": "Ainda não há partidas suficientes para análise. Jogue pelo menos 3 partidas!"}

    def analyze_game(moves):
        """Analisa uma partida e retorna estatísticas de qualidade."""
        stockfish.set_position([])
        good_moves, blunders, total_moves = 0, 0, len(moves)

        for i, move in enumerate(moves):
            stockfish.set_position(moves[:i + 1])

            best_move = stockfish.get_best_move()
            evaluation_before = stockfish.get_evaluation()
            stockfish.make_moves_from_current_position([move])
            evaluation_after = stockfish.get_evaluation()

            eval_diff = evaluation_before["value"] - evaluation_after["value"]

            if best_move == move:
                good_moves += 1  # Jogada perfeita
            elif eval_diff > 200:
                blunders += 1  # Erro grave
            elif eval_diff > 100:
                blunders += 0.5  # Pequeno erro

        return {
            "good_moves": good_moves,
            "blunders": blunders,
            "total_moves": total_moves
        }

    # Analisa as três últimas partidas
    analysis = [analyze_game(game) for game in game_history]

    def calc_percentage_change(old, new):
        """Calcula a porcentagem de mudança entre duas partidas."""
        if old == 0:
            return 100 if new > 0 else 0  # Se não houver referência anterior
        return round(((new - old) / old) * 100, 2)

    # Compara a última partida com as duas anteriores
    progress = {
        "improvement_from_last": {
            "good_moves": calc_percentage_change(analysis[1]["good_moves"], analysis[2]["good_moves"]),
            "blunders": calc_percentage_change(analysis[1]["blunders"], analysis[2]["blunders"]),
            "total_moves": calc_percentage_change(analysis[1]["total_moves"], analysis[2]["total_moves"])
        },
        "improvement_from_two_games_ago": {
            "good_moves": calc_percentage_change(analysis[0]["good_moves"], analysis[2]["good_moves"]),
            "blunders": calc_percentage_change(analysis[0]["blunders"], analysis[2]["blunders"]),
            "total_moves": calc_percentage_change(analysis[0]["total_moves"], analysis[2]["total_moves"])
        }
    }

    return {
        "message": "Comparação realizada!",
        "progress": progress
    }

# ROTAS A SEREM USADAS AO PENSAR EM INTEGRAR COM O ROBO
@app.get("/get_position/{square}", tags=['ROBOT'])
def get_position(square: str):
    """ Converte uma posição do tabuleiro de xadrez (ex: 'h1') para coordenadas numéricas (x, y). """
    
    if len(square) != 2 or square[0] not in "abcdefgh" or square[1] not in "12345678":
        raise HTTPException(status_code=400, detail="Posição inválida! Use notação padrão, ex: 'h1'.")

    # Mapeamento das colunas (a-h) para valores X
    column_map = {
        "a": 1000, "b": 2000, "c": 3000, "d": 4000,
        "e": 5000, "f": 6000, "g": 7000, "h": 8000
    }
    
    # Mapeamento das linhas (1-8) para valores Y
    row_map = {
        "1": 1000, "2": 2000, "3": 3000, "4": 4000,
        "5": 5000, "6": 6000, "7": 7000, "8": 8000
    }

    # Obtendo valores X e Y
    x = column_map[square[0]]
    y = row_map[square[1]]

    return {"square": square, "x": x, "y": y}

# Rotas de conexão DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/register/",tags=['DB'])
def create_user(payload: baseModels.UserRegister, db: Session = Depends(get_db)):
    print("payload", payload)
    
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = bcrypt.hash(payload.password)

    new_user = User(username=payload.username, password=hashed_password, email=payload.email)
    db.add(new_user)
    db.commit()

    return {
        "message": "User created successfully", 
        "id": new_user.id
    }

@app.get("/get-users/", tags=['DB'])
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(desc(User.rating)).all()

    return [
        {
            "username": user.username,
            "rating": user.rating
        }
        for user in users
    ]

@app.post("/login/", tags=['DB'])
def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not bcrypt.verify(password, user.password):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    # Gerar token JWT
    expiration = datetime.utcnow() + timedelta(hours=1)
    token = jwt.encode({"id": user.id, "exp": expiration}, str(SECRET_KEY), algorithm=ALGORITHM)
    
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
def forgot_password(email: str, db: Session = Depends(get_db)):
    """ Verifica se o e-mail existe e envia um link de recuperação """
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="E-mail não encontrado.")
    
    # Gerar token de redefinição de senha
    reset_token = create_reset_token(email)
    
    # Enviar e-mail com link
    send_reset_email(email, reset_token)
    
    return {"message": "E-mail de redefinição de senha enviado!"}
