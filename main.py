from fastapi import FastAPI, Depends, HTTPException, Security, Header, BackgroundTasks, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from fastapi.responses import JSONResponse
from jwt import ExpiredSignatureError, DecodeError
from uuid import uuid4
from starlette.status import HTTP_400_BAD_REQUEST
from chess import Board
from dateutil import parser


from Model.users import User
from Model.games import Game
from Model.moves import Move
from Model.evaluation import Evaluation
from Model.robotToken import RobotToken

import jwt
import math
import time
import math
import os
import smtplib
import chess
import chess.engine
import socketio
import asyncio
import json
from typing import Dict, List, Optional

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

app = FastAPI(
    title="Pychess",
    description="API com autenticação JWT",
    version="1.0",
    openapi_tags=[{"name": "DB", "description": "Rotas que acessam o banco de dados"}],
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configurar os domínios permitidos (origens permitidas)
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app_socket = socketio.ASGIApp(sio, other_asgi_app=app)

with open("game-states.json", 'r') as file:
    game_states = json.load(file)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Pychess",
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

load_dotenv(override=True)

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

if not STOCKFISH_PATH:
    raise ValueError("A variável de ambiente STOCKFISH_PATH não está definida")

security = HTTPBearer()

# Inicializa o motor Stockfish
stockfish = Stockfish(STOCKFISH_PATH)
stockfish.set_skill_level(10)  # Ajuste o nível de habilidade (0-20)
stockfish.set_depth(15)  # Profundidade de busca

# Variável para armazenar o histórico do jogo
board = chess.Board()

modo_robo_ativo = False

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

# Lista global para armazenar até 3 últimas partidas
game_history = []

def fen_to_matrix(fen):
    """Converte um FEN em uma matriz 8x8 representando o tabuleiro."""
    rows = fen.split(" ")[0].split("/")  # Pegamos apenas a parte do tabuleiro no FEN
    board_matrix = []

    for row in rows:
        board_row = []
        for char in row:
            if char.isdigit():
                board_row.extend(["."] * int(char))  # Espaços vazios
            else:
                board_row.append(char)  # Peça
        board_matrix.append(board_row)

    return board_matrix

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security), db: Session = Depends(get_db)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        user_id = payload.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/set_difficulty/",tags=['GAME'])
def set_difficulty(level: str):
    """Define o nível de dificuldade do Stockfish"""
    
    difficulty_settings = {
        "muito_baixa": {"skill": 1, "depth": 2, "rating": 150},
        "baixa": {"skill": 2, "depth": 4, "rating": 300},
        "media": {"skill": 5, "depth": 8, "rating": 600},
        "dificil": {"skill": 10, "depth": 14, "rating": 1200},
        "extremo": {"skill": 20, "depth": 22, "rating": "MAX"}
    }

    level = level.lower()
    
    if level not in difficulty_settings:
        raise HTTPException(status_code=400, detail="Nível inválido! Escolha entre: muito_baixa, baixa, media, dificil, extremo.")

    settings = difficulty_settings[level]

    stockfish.set_skill_level(settings["skill"])
    stockfish.set_depth(settings["depth"])

    return {
        "message": f"Dificuldade ajustada para '{level}'",
        "skill_level": settings["skill"],
        "depth": settings["depth"],
        "rating": settings["rating"]
    }

# @app.post("/finish_game/")
# def finish_game(
#     user_id: int = Query(..., description="ID do usuário logado"),
#     winner: str = Query(..., description="'player' ou 'ai'"),
#     db: Session = Depends(get_db)
# ):
#     """
#     Atualiza o status da última partida em andamento do usuário.
#     """
#     game = db.query(Game)\
#              .filter(Game.user_id == user_id, Game.status == game_states["IN_PROGRESS"])\
#              .order_by(Game.id.desc())\
#              .first()

#     if not game:
#         raise HTTPException(status_code=404, detail="Nenhuma partida em andamento encontrada.")

#     if winner == "player":
#         game.status = game_states["PLAYER_WIN"]
#     elif winner == "ai":
#         game.status = game_states["AI_WIN"]
#     else:
#         raise HTTPException(status_code=400, detail="Valor de 'winner' inválido. Use 'player' ou 'ai'.")

#     db.commit()
#     return {"message": f"Partida finalizada. Vencedor: {winner}", "game_id": game.id, "status": game.status}

@app.post("/start_game/", tags=['GAME'])
def start_game(user_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """ Inicia um novo jogo de xadrez e registra a posição inicial. """
    
    # Verifica se há algum jogo em andamento
    existing_game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()
    if existing_game:
        raise HTTPException(status_code=400, detail="Já existe um jogo em andamento!")

    # Criar um novo jogo
    new_game = Game(
        user_id=user_id,
        begin_time=datetime.now()  # ✅ Corrigido: passa datetime, não string
    )
    db.add(new_game)
    db.commit()
    db.refresh(new_game)

    # Iniciar posição no Stockfish
    stockfish.set_position([])  # posição inicial padrão

    # Criar jogada inicial na tabela moves
    initial_move = Move(
        is_player=None,  # Nenhuma jogada ainda
        move="",  # Movimento vazio (início do jogo)
        board_string=stockfish.get_fen_position(),  # FEN da posição inicial
        mv_quality=None,  # Não se aplica ainda
        game_id=new_game.id
    )
    db.add(initial_move)
    db.commit()

    # Avaliação inicial
    new_eval = Evaluation(
        game_id=new_game.id,
        evaluation=0,
        depth=0,
        win_probability_white=50,
        win_probability_black=50,
    )
    db.add(new_eval)
    db.commit()

    return {
        "message": "Jogo iniciado!",
        "game_id": new_game.id,
        "board": stockfish.get_board_visual()
    }

@app.post("/load_game/", tags=['GAME'])
def load_game(game_id: int, db: Session = Depends(get_db)):
    """ Carrega um jogo salvo do banco de dados e atualiza o tabuleiro. """
    
    # Busca o jogo pelo ID
    game = db.query(Game).filter(Game.id == game_id).first()
    
    if not game:
        raise HTTPException(status_code=404, detail="Jogo não encontrado!")

    # Obtém os movimentos associados ao jogo, ordenados pela sequência correta
    moves = db.query(Move.move).filter(Move.game_id == game.id).order_by(Move.id).all()
    moves = [m.move for m in moves]  # Converte para uma lista de strings

    # Configura o Stockfish com os movimentos do jogo carregado
    stockfish.set_position(moves)

    return {
        "message": f"Jogo {game_id} carregado!",
        "board": stockfish.get_board_visual().split("\n")  # Divide em linhas para exibição
    }

@app.get("/game_state_per_moviment/", tags=['GAME'])
def get_game_state_per_moviment(game_id: int, move_number: int, db: Session = Depends(get_db)):
    """ Retorna o estado do tabuleiro após um número específico de jogadas. """
    
    # Busca o jogo pelo ID
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Jogo não encontrado!")

    # Obtém os movimentos até o número especificado
    moves = (
        db.query(Move.move)
        .filter(Move.game_id == game.id)
        .order_by(Move.id)
        .limit(move_number)
        .all()
    )
    moves = [m.move for m in moves]  # Converte para lista de strings

    # Se não houver jogadas, retorna o tabuleiro inicial
    if not moves:
        stockfish.set_position([])  # Reseta o tabuleiro
    else:
        stockfish.set_position(moves)

    return {
        "message": f"Jogo {game_id} após {move_number} jogadas.",
        "board": stockfish.get_board_visual().split("\n")  # Divide para exibição
    }

@app.get("/game_moves/{game_id}", tags=["GAME"])
def get_game_moves_by_id(game_id: int, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Jogo não encontrado.")

    moves = db.query(Move).filter(Move.game_id == game.id).order_by(Move.id).all()
    move_list = [m.move for m in moves]

    return {"moves": move_list}

@app.get("/game_board/", tags=['GAME'])
def get_game_board(db: Session = Depends(get_db)):
    """ Retorna a visualização do tabuleiro baseado no último estado salvo no banco. """

    # Obtém o último jogo ativo e seu último movimento em uma única consulta
    last_game = (
        db.query(Game.id, Move.board_string)
        .join(Move, Move.game_id == Game.id)
        .filter(Game.status == game_states["IN_PROGRESS"])
        .order_by(Game.id.desc(), Move.id.desc())
        .first()
    )

    if not last_game:
        raise HTTPException(status_code=404, detail="Nenhum jogo ativo ou jogada encontrada.")

    game_id, fen_string = last_game

    # Validação do FEN antes de enviar para o Stockfish
    if not fen_string or len(fen_string.split()) != 6:
        raise HTTPException(status_code=400, detail="FEN inválido no banco de dados.")

    # Define a posição no Stockfish
    try:
        stockfish.set_fen_position(fen_string)
        board_visual = stockfish.get_board_visual()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar tabuleiro: {str(e)}")

    if not board_visual:
        raise HTTPException(status_code=500, detail="Falha ao gerar visualização do tabuleiro.")

    return {
        "board": board_visual.split("\n"),
        "fen": fen_string
    }



# @app.post("/finish_game/", tags=["GAME"])
# def finish_game(
#     user_id: int = Query(..., description="ID do usuário logado"),
#     winner: str = Query(..., description="Quem venceu: 'player' ou 'ai'"),
#     db: Session = Depends(get_db)
# ):
#     """
#     Atualiza o status do jogo atual como encerrado.
#     """
#     game = db.query(Game).filter(Game.user_id == user_id, Game.status == game_states["IN_PROGRESS"]).first()
#     if not game:
#         raise HTTPException(status_code=404, detail="Nenhum jogo ativo encontrado para encerrar.")

#     if winner == "player":
#         game.status = game_states["PLAYER_WIN"]
#     elif winner == "ai":
#         game.status = game_states["AI_WIN"]
#     else:
#         raise HTTPException(status_code=400, detail="Parâmetro 'winner' inválido. Use 'player' ou 'ai'.")

#     db.commit()
#     return {"message": "Status do jogo atualizado com sucesso.", "status": game.status}


class MoveData(BaseModel):
    move: str
    isPlayer: int
    fen: str

@app.post("/register_move/", tags=["GAME"])
async def register_move(
    moves: List[MoveData],
    db: Session = Depends(get_db),
    user_id: int = Query(..., description="ID do usuário logado"),
    winner: str | None = Query(None, description="Pode ser 'PLAYER' ou 'AI'"),
):
    """
    Registra várias jogadas de uma só vez e finaliza o jogo (opcionalmente com o vencedor).
    """
    # ✅ Busca jogo ativo
    game = db.query(Game).filter(
        Game.user_id == user_id,
        Game.status == game_states["IN_PROGRESS"]
    ).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado.")

    # ✅ Cria os registros de jogadas
    for move in moves:
        new_move = Move(
            game_id=game.id,
            move=move.move,
            is_player=bool(move.isPlayer),
            board_string=move.fen,
            created_at=datetime.now(),  # ✅ Corrigido: datetime, não string
        )
        db.add(new_move)

    db.commit()

    # ✅ Atualiza o status do jogo e a data de término
    if winner:
        if winner.upper() == "PLAYER":
            game.status = game_states["PLAYER_WIN"]
        elif winner.upper() == "AI":
            game.status = game_states["AI_WIN"]

        game.end_time = datetime.now()  # ✅ Marca quando o jogo terminou
        db.commit()

    return {
        "message": f"{len(moves)} jogadas registradas com sucesso!",
        "game_id": game.id,
        "winner": winner or "IN_PROGRESS",
        "end_time": game.end_time
    }


@app.post("/play_game/", tags=['GAME'])
async def play_game(
    move: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Query(..., description="ID do usuário logado")
):
    """ O usuário joga, e o Stockfish responde. A primeira jogada das pretas é forçada. """

    # 🔧 Jogada das pretas fixa para a primeira vez que o Stockfish joga
    FORCED_FIRST_BLACK_MOVE = "e7e6"

    # -----------------------------------------------------------
    # Carregar jogo
    # -----------------------------------------------------------
    game = db.query(Game).filter(
        Game.user_id == user_id,
        Game.status == game_states["IN_PROGRESS"]
    ).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Último estado salvo
    last_move = db.query(Move).filter(Move.game_id == game.id).order_by(Move.id.desc()).first()

    board = chess.Board(last_move.board_string) if last_move else chess.Board()

    # -----------------------------------------------------------
    # Jogada do player
    # -----------------------------------------------------------
    if move not in [m.uci() for m in board.legal_moves]:
        raise HTTPException(status_code=400, detail="Movimento do jogador inválido!")

    board.push(chess.Move.from_uci(move))
    stockfish.set_fen_position(board.fen())

    # Classificação do movimento
    analysis = analyze_move(move, db)
    classification = analysis["classification"]

    # Salvar jogada do jogador
    new_move = Move(
        is_player=True,
        move=move,
        board_string=board.fen(),
        mv_quality=classification,
        game_id=game.id,
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    db.add(new_move)
    db.commit()

    # Verifica xeque-mate do jogador
    if board.is_checkmate():
        game.status = game_states["PLAYER_WIN"]
        db.commit()
        rating(game.user_id)

        return {
            "message": "Xeque-mate! Brancas venceram!",
            "board_fen": board.fen(),
            "player_move": move,
            "stockfish_move": None,
            "winner": "player"
        }

    # -----------------------------------------------------------
    # Jogada do Stockfish (PRETAS)
    # -----------------------------------------------------------
    total_moves = db.query(Move).filter(Move.game_id == game.id).count()

    # Jogada forçada das pretas
    print(f'total moves: {total_moves}, do tipo {type(total_moves)}')
    # stockfish_move_uci = FORCED_FIRST_BLACK_MOVE
    if total_moves <= 2:
        # Jogada forçada das pretas
        stockfish_move_uci = FORCED_FIRST_BLACK_MOVE
    else:
        # Jogada normal do Stockfish
        stockfish_move_uci = stockfish.get_best_move()

    stockfish_move = chess.Move.from_uci(stockfish_move_uci)

    # Aplica direto SEM verificações adicionais
    board.push(stockfish_move)
    stockfish.set_fen_position(board.fen())

    # Salvar jogada do Stockfish
    sf_move = Move(
        is_player=False,
        move=stockfish_move_uci,
        board_string=board.fen(),
        game_id=game.id,
        mv_quality=None,
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    db.add(sf_move)
    db.commit()

    # Xeque-mate após jogada das pretas
    if board.is_checkmate():
        game.status = game_states["AI_WIN"]
        db.commit()
        rating(game.user_id)

        return {
            "message": "Xeque-mate! Pretas venceram!",
            "board_fen": board.fen(),
            "player_move": move,
            "stockfish_move": stockfish_move_uci,
            "winner": "ai"
        }

    # -----------------------------------------------------------
    # Avaliação
    # -----------------------------------------------------------
    background_tasks.add_task(calculate_and_save_evaluation, game.id, db)

    await sio.emit("board_updated")

    return {
        "message": "Movimentos realizados!",
        "board_fen": board.fen(),
        "player_move": move,
        "stockfish_move": stockfish_move_uci
    }

def calculate_and_save_evaluation(game_id: int, db: Session):
    moves = db.query(Move.move).filter(Move.game_id == game_id).order_by(Move.id).all()
    move_list = [m.move for m in moves]
    stockfish.set_position(move_list)

    best_eval = None
    best_depth = 0

    for depth in range(8, 13):
        stockfish.set_depth(depth)
        evaluation = stockfish.get_evaluation()

        if best_eval is None or abs(evaluation["value"]) > abs(best_eval["value"]):
            best_eval = evaluation
            best_depth = depth

    if best_eval["type"] == "mate":
        if best_eval["value"] > 0:
            win_white = 100
        else:
            win_white = 0
    else:
        cp = best_eval["value"]
        win_white = round((1 / (1 + math.exp(-0.004 * cp))) * 100, 2)

    win_black = round(100 - win_white, 2)

    existing = db.query(Evaluation).filter(Evaluation.game_id == game_id).first()
    if existing:
        existing.evaluation = best_eval["value"]
        existing.depth = best_depth
        existing.win_probability_white = win_white
        existing.win_probability_black = win_black
        existing.last_updated = datetime.utcnow()
    else:
        new_eval = Evaluation(
            game_id=game_id,
            evaluation=best_eval["value"],
            depth=best_depth,
            win_probability_white=win_white,
            win_probability_black=win_black,
        )
        db.add(new_eval)

    db.commit()

@app.get("/evaluate_position/", tags=['GAME'])
def evaluate_position(db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()
    if not game:
        raise HTTPException(status_code=404, detail="Nenhum jogo ativo encontrado.")

    evaluation = db.query(Evaluation).filter(Evaluation.game_id == game.id).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Nenhuma avaliação disponível ainda.")

    return {
        "evaluation": evaluation.evaluation,
        "best_depth": evaluation.depth,
        "win_probability_white": evaluation.win_probability_white,
        "win_probability_black": evaluation.win_probability_black,
        "last_updated": evaluation.last_updated,
    }

@app.get("/game_moves/", tags=["GAME"])
def get_game_moves(db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()
    if not game:
        raise HTTPException(status_code=404, detail="Nenhum jogo ativo encontrado.")
    
    moves = db.query(Move).filter(Move.game_id == game.id).order_by(Move.id).all()
    move_list = [m.move for m in moves]
    
    return {"moves": move_list}

@app.post("/rating/", tags=['GAME'])
def rating(user_id: int, db: Session = Depends(get_db)):
    """Avalia o jogo completo armazenado em game_moves e atualiza o rating do jogador no banco de dados."""

    global stockfish

    game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()

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
def analyze_move(move: str,  db: Session = Depends(get_db)):
    """ Analisa a jogada, comparando com a melhor possível. """

     # Verifica se existe um jogo ativo
    game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings

    stockfish.set_position(game_moves)

    # Obtém a melhor jogada recomendada pelo Stockfish
    best_move = stockfish.get_best_move()

    if not stockfish.is_move_correct(move):
        raise HTTPException(status_code=400, detail="Movimento inválido!")

    # Avaliação antes da jogada
    eval_before = stockfish.get_evaluation()
    eval_before_score = eval_before["value"] if eval_before["type"] == "cp" else 0

    # Aplica o movimento do usuário
    game_moves.append(move)
    stockfish.set_position(game_moves)

    # Avaliação após a jogada
    eval_after = stockfish.get_evaluation()
    eval_after_score = eval_after["value"] if eval_after["type"] == "cp" else 0

    # Desfaz o movimento do usuário e testa a melhor jogada do Stockfish
    game_moves.pop()
    stockfish.set_position(game_moves)
    game_moves.append(best_move)
    stockfish.set_position(game_moves)

    # Avaliação após a melhor jogada do Stockfish
    eval_best = stockfish.get_evaluation()
    eval_best_score = eval_best["value"] if eval_best["type"] == "cp" else 0

    # Calcula a diferença entre as avaliações
    diff_user = eval_after_score - eval_before_score  # O quanto a jogada do usuário melhorou ou piorou a posição
    diff_best = eval_best_score - eval_before_score  # O quanto a melhor jogada melhoraria a posição
    diff_to_best = diff_user - diff_best  # Diferença entre a jogada do usuário e a melhor jogada

    # Classificação da jogada
    if diff_to_best == 0:
        classification = "Brilhante 💎"
    elif -30 <= diff_to_best < 0:
        classification = "Boa ✅"
    elif -100 <= diff_to_best < -30:
        classification = "Ok 🤷"
    else:
        classification = "Gafe ❌"

    return {
        "move": move,
        "best_move": best_move,
        "evaluation_before": eval_before_score,
        "evaluation_after": eval_after_score,
        "evaluation_best_move": eval_best_score,
        "classification": classification,
        "board": stockfish.get_board_visual()
    }

@app.get("/game_history/",tags=['GAME'])
def game_history(db: Session = Depends(get_db)):
    """ Retorna o histórico de jogadas do jogo atual. """
    game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings

    return {"moves": game_moves}

@app.get("/last_game/", tags=["GAME"])
async def get_last_game(
    user_id: int = Query(...),
    db: Session = Depends(get_db)
):
    last_game = (
        db.query(Game)
        .filter(
            Game.user_id == user_id,
            Game.status.in_([game_states["AI_WIN"], game_states["PLAYER_WIN"]])
        )
        .order_by(Game.id.desc())
        .first()
    )

    if not last_game:
        return JSONResponse(content={"detail": "Nenhuma partida encontrada."}, status_code=404)

    user = db.query(User).filter(User.id == user_id).first()
    username = user.username if user else "Desconhecido"

    result = "Derrota" if last_game.status == game_states["AI_WIN"] else "Vitória"

    # -----------------------------
    # 🔥 DURAÇÃO DIRETA: end_time - begin_time
    # -----------------------------
    duration_str = "00:00:00"
    if last_game.begin_time and last_game.end_time:
        duration = last_game.end_time - last_game.begin_time

        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return {
        "username": username,
        "result": result,
        "duration": duration_str,
        "id": last_game.id
    }

@app.post("/evaluate_progress/", tags=['GAME'])
def evaluate_progress(db: Session = Depends(get_db)):
    """Compara as três últimas partidas e verifica a evolução do jogador."""
    global game_history

    game = db.query(Game).filter(Game.status == game_states["IN_PROGRESS"]).first()

    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings

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

class MoveRequest(BaseModel):
    move: str

games = {}
active_games: Dict[str, chess.Board] = {}

@app.post("/play_autonomous_game/", tags=['GAME'])
async def play_autonomous_game(move_req: MoveRequest, game_id: str = Query(...)):
    move = move_req.move

    global active_games

    if game_id not in active_games:
        active_games[game_id] = chess.Board()

    board = active_games[game_id]

    if board.is_game_over():
        board.reset()

    if move not in [m.uci() for m in board.legal_moves]:
        return {
            "fen": board.fen(),
            "status": "invalid",
            "error": "Movimento do jogador inválido!",
            "player_move": move,
            "stockfish_move": None
        }

    board.push(chess.Move.from_uci(move))

    if board.is_checkmate():
        return {
            "fen": board.fen(),
            "status": "fim",
            "message": "Xeque-mate! Brancas venceram!",
            "player_move": move,
            "stockfish_move": None,
            "winner": "player"
        }

    stockfish.set_fen_position(board.fen())
    best_move = stockfish.get_best_move()

    if best_move and chess.Move.from_uci(best_move) in board.legal_moves:
        board.push(chess.Move.from_uci(best_move))
        stockfish.set_fen_position(board.fen())

        if board.is_checkmate():
            return {
                "fen": board.fen(),
                "status": "fim",
                "message": "Xeque-mate! Pretas venceram!",
                "player_move": move,
                "stockfish_move": best_move,
                "winner": "ai"
            }

    return {
        "fen": board.fen(),
        "status": "ok",
        "player_move": move,
        "stockfish_move": best_move
    }

# ROTAS A SEREM USADAS AO PENSAR EM INTEGRAR COM O ROBO
@app.get("/get_position/{square}", tags=['ROBOT'])
def get_move_vector(move: str):
    """
    Recebe uma jogada como 'h2h3' e retorna o deslocamento em X, Y
    e o ângulo inteiro que o robô deve girar a partir da posição 0 (referência horizontal).
    """

    if len(move) != 4:
        raise HTTPException(status_code=400, detail="Jogada inválida! Use formato padrão, ex: 'h2h3'.")

    from_square = move[:2]
    to_square = move[2:]

    def get_position(square: str):
        if len(square) != 2 or square[0] not in "abcdefgh" or square[1] not in "12345678":
            raise HTTPException(status_code=400, detail=f"Posição inválida: {square}")

        column_map = {
            "a": 1000, "b": 2000, "c": 3000, "d": 4000,
            "e": 5000, "f": 6000, "g": 7000, "h": 8000
        }

        row_map = {
            "1": 1000, "2": 2000, "3": 3000, "4": 4000,
            "5": 5000, "6": 6000, "7": 7000, "8": 8000
        }

        x = column_map[square[0]]
        y = row_map[square[1]]
        return (x, y)

    # Posições de origem e destino
    x1, y1 = get_position(from_square)
    x2, y2 = get_position(to_square)

    # Vetor de deslocamento
    dx = x2 - x1
    dy = y2 - y1

    # Ângulo absoluto (em relação ao eixo X positivo) — referência 0°
    angle_rad = math.atan2(dy, dx)
    angle_deg = int(round(math.degrees(angle_rad)))

    # Corrige ângulos negativos para o intervalo 0°–359°
    if angle_deg < 0:
        angle_deg += 360

    return {
        "from": from_square,
        "to": to_square,
        "dx": dx,
        "dy": dy,
        "angle_deg": angle_deg  # usado sempre a partir da posição 0
    }

@app.get("/get-robo-mode/", tags=['ROBOT'])
def get_robo_mode():
    global modo_robo_ativo

    return {"robo_mode": modo_robo_ativo}

@app.post("/set-robo-mode/", tags=['ROBOT'])
def set_robo_mode(data: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    global modo_robo_ativo
    ativo = data.get("ativo")
    if ativo is None:
        raise HTTPException(status_code=400, detail="Campo 'ativo' obrigatório")
    modo_robo_ativo = bool(ativo)
    return {"status": "ok", "robo_mode": modo_robo_ativo}


def send_email(email: str, token: str):
    msg = MIMEMultipart()
    msg["From"] = os.getenv("SMTP_EMAIL")
    msg["To"] = email
    msg["Subject"] = "Token para ativar modo Robô"

    body = f"""
    <p>Olá,</p>
    <p>Você solicitou ativar o modo robô em sua plataforma de xadrez.</p>
    <p>Seu token de verificação é:</p>
    <h2>{token}</h2>
    <p>Copie e cole esse código no campo solicitado. Este token é válido por tempo limitado e só pode ser usado uma vez.</p>
    <p>Se você não solicitou isso, ignore este e-mail.</p>
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

@app.post("/generate-robo-token/", tags=['ROBOT'])
def generate_robo_token(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sete_dias_atras = datetime.utcnow() - timedelta(days=7)

        # Verifica se já existe um token usado nos últimos 7 dias
        existing_token = db.query(RobotToken).filter(
            RobotToken.user_id == user.id,
            RobotToken.used == True,
            RobotToken.created_at >= sete_dias_atras
        ).order_by(RobotToken.created_at.desc()).first()

        if existing_token:
            global modo_robo_ativo
            modo_robo_ativo = True

            return {"message": "Token já utilizado nos últimos 7 dias, modo robô já foi ativado recentemente."}

        # Caso não exista, gerar novo token
        token_str = str(uuid4()).split("-")[0]
        token = RobotToken(user_id=user.id, token=token_str)
        db.add(token)
        db.commit()

        send_email(user.email, token_str)

        return {"message": "Token enviado para seu e-mail"}

    except Exception as e:
        print("❌ ERRO AO GERAR TOKEN:", e)
        raise HTTPException(status_code=500, detail="Erro interno ao gerar token")

@app.post("/validate-robo-token/", tags=['ROBOT'])
def validate_robo_token(data: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token_str = data.get('token')
    token = db.query(RobotToken).filter_by(user_id=user.id, token=token_str, used=False).first()
    
    if not token:
        raise HTTPException(status_code=400, detail="Token inválido")

    token.used = True
    db.commit()

    # Ativar modo robô global (ou por usuário, como preferir)
    global modo_robo_ativo
    modo_robo_ativo = True

    return {"message": "Modo robô ativado"}


# Rotas de conexão DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/verify-token/", tags=['DB'])
def verify_token(token: str):
    try:
        payload = jwt.decode(token, str(SECRET_KEY), algorithms=[ALGORITHM])
        return {"valid": True, "user_id": payload["id"]}
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado.")
    except DecodeError:
        raise HTTPException(status_code=401, detail="Token inválido.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: EmailStr

@app.post("/new-users/",tags=['DB'])
def create_user(user: CreateUserRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = bcrypt.hash(user.password)

    new_user = User(username=user.username, password=hashed_password, email=user.email)
    db.add(new_user)
    db.commit()

    return {
        "message": "User created successfully", 
        "id": new_user.id
    }

@app.get("/get-users/", tags=['DB'])
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    user_list = []

    for user in users:
        # Busca todas as partidas do usuário
        games = db.query(Game).filter(Game.user_id == user.id).all()

        # Faz a contagem de resultados
        wins = sum(1 for g in games if g.status == game_states["PLAYER_WIN"])
        losses = sum(1 for g in games if g.status == game_states["AI_WIN"])

        # Calcula o rating dinamicamente
        rating = wins - losses

        user_list.append({
            "username": user.username,
            "rating": rating
        })

    # Ordena pelo rating (maior primeiro)
    sorted_users = sorted(user_list, key=lambda x: x["rating"], reverse=True)
    return sorted_users


class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login/", tags=['DB'])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not bcrypt.verify(payload.password, user.password):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    expiration = datetime.utcnow() + timedelta(hours=48)
    token = jwt.encode({"id": user.id, "exp": expiration}, str(SECRET_KEY), algorithm=ALGORITHM)

    return {"message": "Login successful", "token": token, "user_id": user.id}

@app.get("/user-session/", tags=['DB'])
def get_user_info(
    user_id: int | None = Query(None, description="ID do usuário a buscar (opcional)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna informações do usuário e estatísticas de partidas calculadas dinamicamente,
    incluindo o tempo médio de jogo (em minutos).
    """

    # ✅ Se um user_id for passado, buscar o usuário correspondente
    if user_id is not None:
        db_user = db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        user = db_user

    # ✅ Busca todas as partidas do usuário
    games = db.query(Game).filter(Game.user_id == user.id).all()

    # ✅ Calcula estatísticas básicas
    wins = sum(1 for g in games if g.status == game_states["PLAYER_WIN"])
    losses = sum(1 for g in games if g.status == game_states["AI_WIN"])
    draws = sum(1 for g in games if g.status == game_states["DRAW"])
    total_games = len(games)

    # ✅ Calcula tempo médio de jogo (somente partidas com begin_time e end_time válidos)
    times = [
        (g.end_time - g.begin_time).total_seconds()
        for g in games
        if g.begin_time and g.end_time
    ]

    average_game_time = round(sum(times) / len(times) / 60, 2) if times else 0.0

    # ✅ Retorna dados combinados
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "total_games": total_games,
        "rating": user.rating,
        "averageGameTime": average_game_time,  # em minutos
    }


@app.get("/user-history/", tags=["GAME"])
def get_user_history(
    user_id: int = Query(..., description="ID do usuário logado"),
    db: Session = Depends(get_db)
):
    """
    Retorna o histórico de partidas do usuário, incluindo resultado e duração.
    """

    games = (
        db.query(Game)
        .filter(Game.user_id == user_id)
        .order_by(Game.id.desc())
        .all()
    )

    if not games:
        return JSONResponse(
            content={"detail": "Nenhuma partida encontrada."},
            status_code=404
        )

    user = db.query(User).filter(User.id == user_id).first()
    username = user.username if user else "Desconhecido"

    result_list = []

    for game in games:
        if game.status == game_states["AI_WIN"]:
            result = "Derrota"
        elif game.status == game_states["PLAYER_WIN"]:
            result = "Vitória"
        else:
            result = "Em andamento"

        duration_str = "00:00:00"

        if game.begin_time and game.end_time:
            try:
                begin_dt = parser.parse(game.begin_time) if isinstance(game.begin_time, str) else game.begin_time
                end_dt = parser.parse(game.end_time) if isinstance(game.end_time, str) else game.end_time

                duration = end_dt - begin_dt
                total_seconds = int(duration.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60

                duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            except Exception as e:
                print(f"Erro ao calcular duração do jogo {game.id}: {e}")
                duration_str = "00:00:00"

        result_list.append({
            "id": game.id,
            "username": username,
            "result": result,
            "duration": duration_str
        })

    return result_list


@app.get("/game-info/{game_id}", tags=["GAME"])
def get_game_info(game_id: int, db: Session = Depends(get_db)):
    """
    Retorna informações detalhadas de uma partida específica.
    Inclui resultado e duração com base no begin_time e end_time.
    """
    game = db.query(Game).filter(Game.id == game_id).first()

    if not game:
        return JSONResponse(
            content={"detail": "Partida não encontrada."},
            status_code=404
        )

    # Determina o resultado
    if game.status == game_states["AI_WIN"]:
        result = "Derrota"
    elif game.status == game_states["PLAYER_WIN"]:
        result = "Vitória"
    else:
        result = "Em andamento"

    # Calcula a duração com base em begin_time e end_time
    duration_str = "00:00:00"
    if game.begin_time and game.end_time:
        try:
            duration = game.end_time - game.begin_time
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        except Exception:
            duration_str = "00:00:00"

    return {
        "result": result,
        "duration": duration_str
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
