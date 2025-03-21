from fastapi import FastAPI, Depends, HTTPException, Security
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

from Model.users import User
from Model.games import Game
from Model.moves import Move

import jwt
import math
import time
import math
import os
import smtplib
import chess
import chess.engine

app = FastAPI(
    title="Minha API",
    description="API com autenticação JWT",
    version="1.0",
    openapi_tags=[{"name": "DB", "description": "Rotas que acessam o banco de dados"}],
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
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

STOCKFISH_PATH = r"C:\Users\joao.silva\OneDrive - Allparts Componentes Ltda\Documentos\GitHub\Pychess-API\stockfish\stockfish-windows-x86-64-avx2.exe"
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

security = HTTPBearer()

# Inicializa o motor Stockfish
stockfish = Stockfish(STOCKFISH_PATH)
stockfish.set_skill_level(10)  # Ajuste o nível de habilidade (0-20)
stockfish.set_depth(15)  # Profundidade de busca

# Variável para armazenar o histórico do jogo
board = chess.Board()

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

@app.post("/start_game/", tags=['GAME'])
def start_game(user_id: int, db: Session = Depends(get_db)):
    """ Inicia um novo jogo de xadrez. """
    
    # Verifica se há algum jogo em andamento
    existing_game = db.query(Game).filter(Game.player_win == 0).first()
    
    if existing_game:
        raise HTTPException(status_code=400, detail="Já existe um jogo em andamento!")

    # Criar um novo jogo
    new_game = Game(user_id=user_id)
    db.add(new_game)
    db.commit()
    db.refresh(new_game)

    # Iniciar posição no Stockfish
    stockfish.set_position([])

    return {"message": "Jogo iniciado!", "game_id": new_game.id, "board": stockfish.get_board_visual()}

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


@app.get("/game_board/", tags=['GAME'])
def get_game_board(db: Session = Depends(get_db)):
    """ Retorna a visualização do tabuleiro baseado no último estado salvo no banco. """

    # Obtém o último jogo ativo e seu último movimento em uma única consulta
    last_game = (
        db.query(Game.id, Move.board_string)
        .join(Move, Move.game_id == Game.id)
        .filter(Game.player_win == 0)
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

    return {"board": board_visual.split("\n")}

@app.post("/play_game/", tags=['GAME'])
def play_game(move: str, db: Session = Depends(get_db)):
    """ O usuário joga, e o Stockfish responde com a melhor jogada, verificando capturas. """

    # Verifica se há um jogo ativo
    game = db.query(Game).filter(Game.player_win == 0).first()
    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém o último estado salvo do tabuleiro
    last_move = db.query(Move).filter(Move.game_id == game.id).order_by(Move.id.desc()).first()

    # Se houver um estado salvo, carregamos ele; caso contrário, criamos um novo tabuleiro
    board = chess.Board(last_move.board_string) if last_move and last_move.board_string else chess.Board()

    # Verifica se a jogada do jogador é válida
    if move not in [m.uci() for m in board.legal_moves]:
        raise HTTPException(status_code=400, detail="Movimento do jogador inválido!")

    # Aplica o movimento do jogador no tabuleiro
    board.push(chess.Move.from_uci(move))

    # Atualiza o Stockfish com o novo estado do jogo
    stockfish.set_fen_position(board.fen())

    # Análise da jogada
    analysis = analyze_move(move, db)
    classification = analysis["classification"]

    # Salva o movimento do jogador no banco
    new_move = Move(
        is_player=True,
        move=move,
        board_string=board.fen(),
        mv_quality=classification,
        game_id=game.id,
    )
    db.add(new_move)
    db.commit()

    # Verifica xeque-mate após o movimento do jogador
    if board.is_checkmate():
        game.player_win = 1  # Brancas venceram
        db.commit()
        rating(game.user_id)

        return {
            "message": "Xeque-mate! Brancas venceram!",
            "board_fen": board.fen(),
            "player_move": move,
            "stockfish_move": None
        }

    # Stockfish responde com o melhor movimento
    best_move = stockfish.get_best_move()
    if best_move:
        stockfish_move = chess.Move.from_uci(best_move)

        # Se for válido, aplicamos no tabuleiro
        if stockfish_move in board.legal_moves:
            board.push(stockfish_move)
            stockfish.set_fen_position(board.fen())

            # Salva a jogada do Stockfish
            sf_move = Move(
                is_player=False,
                move=best_move,
                board_string=board.fen(),
                game_id=game.id,
                mv_quality=None,
            )
            db.add(sf_move)
            db.commit()

            # Verifica xeque-mate após a jogada do Stockfish
            if board.is_checkmate():
                game.player_win = 2  # Pretas venceram
                db.commit()
                rating(game.user_id)

                return {
                    "message": "Xeque-mate! Pretas venceram!",
                    "board_fen": board.fen(),
                    "player_move": move,
                    "stockfish_move": best_move
                }
        else:
            return {
                "message": "Movimento do Stockfish inválido. Tentando novamente...",
                "board_fen": board.fen(),
                "player_move": move,
                "stockfish_move": None
            }

    return {
        "message": "Movimentos realizados!",
        "board_fen": board.fen(),
        "player_move": move,
        "stockfish_move": best_move
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
def analyze_move(move: str,  db: Session = Depends(get_db)):
    """ Analisa a jogada, comparando com a melhor possível. """

     # Verifica se existe um jogo ativo
    game = db.query(Game).filter(Game.player_win == 0).first()

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

@app.post("/new-users/",tags=['DB'])
def create_user(username: str, password: str, email: str, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = bcrypt.hash(password)

    new_user = User(username=username, password=hashed_password, email=email)
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
