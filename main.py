from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from Model.items import Item  
from database.database import SessionLocal, engine

from stockfish import Stockfish

import math
import random

# Criar a tabela no banco (caso não tenha sido criada via Alembic)
Item.metadata.create_all(bind=engine)

app = FastAPI()

STOCKFISH_PATH = r"C:\Users\joao.silva\OneDrive - Allparts Componentes Ltda\Documentos\GitHub\Pychess-API\stockfish\stockfish-windows-x86-64-avx2.exe"

# Inicializa o motor Stockfish
stockfish = Stockfish(STOCKFISH_PATH)
stockfish.set_skill_level(10)  # Ajuste o nível de habilidade (0-20)
stockfish.set_depth(15)  # Profundidade de busca

# Variável para armazenar o histórico do jogo
game_moves = []
saved_games = {}

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

@app.post("/start_game/",tags=['GAME'])
def start_game():
    """ Inicia um novo jogo de xadrez. """
    global game_moves
    game_moves = []  # Reinicia o histórico de jogadas
    stockfish.set_position(game_moves)
    return {"message": "Jogo iniciado!", "board": stockfish.get_board_visual()}

@app.post("/load_game/",tags=['GAME'])
def load_game(game_id: str):
    """ Carrega um jogo salvo. """
    global game_moves
    if game_id not in saved_games:
        raise HTTPException(status_code=404, detail="Jogo não encontrado!")

    game_moves = saved_games[game_id]
    stockfish.set_position(game_moves)
    return {"message": "Jogo carregado!", "board": stockfish.get_board_visual()}

@app.get("/game_board/", tags=['GAME'])
def get_game_board():
    """ Retorna a matriz 8x8 representando o estado atual do jogo. """
    board_visual = stockfish.get_board_visual().split("\n")  # Divide a saída em linhas

    return {"board": board_visual}

@app.post("/play_game/", tags=['GAME'])
def play_game(move: str):
    """ O usuário joga, e o Stockfish responde com a melhor jogada, verificando capturas. """
    global game_moves

    if not stockfish.is_move_correct(move):
        raise HTTPException(status_code=400, detail="Movimento inválido!")

    # Obtém o estado do tabuleiro antes da jogada do usuário
    board_before = stockfish.get_fen_position()

    # Adiciona a jogada do usuário
    game_moves.append(move)
    stockfish.set_position(game_moves)

    # Obtém o estado do tabuleiro depois da jogada do usuário
    board_after = stockfish.get_fen_position()

    # Converte FEN para matriz 8x8 antes e depois do movimento
    board_matrix_before = fen_to_matrix(board_before)
    board_matrix_after = fen_to_matrix(board_after)

    # Verifica se houve captura pelo usuário
    captured_piece_position = None
    captured_piece = None
    moved_piece = None
    from_square, to_square = move[:2], move[2:]  # Exemplo: "e2e4" -> "e2" e "e4"

    row_to, col_to = 8 - int(to_square[1]), ord(to_square[0]) - ord('a')  # Converte para índice da matriz

    if board_matrix_before[row_to][col_to] != "." and board_matrix_after[row_to][col_to] != board_matrix_before[row_to][col_to]:
        captured_piece_position = to_square
        captured_piece = board_matrix_before[row_to][col_to]  # Peça capturada
        moved_piece = board_matrix_after[row_to][col_to]  # Peça que ocupou a casa

    # Stockfish responde
    best_move = stockfish.get_best_move()
    captured_piece_position_stockfish = None
    captured_piece_stockfish = None
    moved_piece_stockfish = None

    if best_move:
        # Obtém o estado do tabuleiro antes do Stockfish jogar
        board_before_stockfish = stockfish.get_fen_position()

        game_moves.append(best_move)
        stockfish.set_position(game_moves)

        # Obtém o estado do tabuleiro depois da jogada do Stockfish
        board_after_stockfish = stockfish.get_fen_position()

        # Converte FEN para matriz 8x8 antes e depois do movimento do Stockfish
        board_matrix_before_sf = fen_to_matrix(board_before_stockfish)
        board_matrix_after_sf = fen_to_matrix(board_after_stockfish)

        # Verifica se houve captura pelo Stockfish
        from_square_sf, to_square_sf = best_move[:2], best_move[2:]

        row_to_sf, col_to_sf = 8 - int(to_square_sf[1]), ord(to_square_sf[0]) - ord('a')

        if board_matrix_before_sf[row_to_sf][col_to_sf] != "." and board_matrix_after_sf[row_to_sf][col_to_sf] != board_matrix_before_sf[row_to_sf][col_to_sf]:
            captured_piece_position_stockfish = to_square_sf
            captured_piece_stockfish = board_matrix_before_sf[row_to_sf][col_to_sf]  # Peça capturada pelo Stockfish
            moved_piece_stockfish = board_matrix_after_sf[row_to_sf][col_to_sf]  # Peça que ficou no lugar

    return {
        "message": "Movimentos realizados!",
        "player_move": move,
        "player_capture": captured_piece_position,
        "captured_piece": captured_piece,
        "moved_piece": moved_piece,
        "stockfish_move": best_move,
        "stockfish_capture": captured_piece_position_stockfish,
        "stockfish_captured_piece": captured_piece_stockfish,
        "stockfish_moved_piece": moved_piece_stockfish,
        "board": stockfish.get_board_visual()
    }




@app.get("/evaluate_position/",tags=['GAME'])
def evaluate_position():
    """ Avalia a posição do tabuleiro com base nos movimentos feitos. """
    global game_moves
    stockfish.set_position(game_moves)  # Garante que estamos avaliando o estado atual

    evaluation = stockfish.get_evaluation()

    if evaluation["type"] == "mate":
        if evaluation["value"] > 0:
            return {"winner": "Brancas", "win_probability": 100, "lose_probability": 0}
        else:
            return {"winner": "Pretas", "win_probability": 100, "lose_probability": 0}

    # Convertendo a vantagem do Stockfish para probabilidade de vitória
    centipawns = evaluation["value"]
    win_probability = 1 / (1 + math.exp(-0.004 * centipawns)) * 100  # Fórmula de conversão

    return {
        "evaluation": centipawns,
        "win_probability_white": round(win_probability, 2),
        "win_probability_black": round(100 - win_probability, 2),
        "board": stockfish.get_board_visual()
    }

@app.post("/analyze_move/",tags=['GAME'])
def analyze_move(move: str):
    """ Analisa a jogada, comparando com a melhor possível. """
    global game_moves
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
def game_history():
    """ Retorna o histórico de jogadas do jogo atual. """
    return {"moves": game_moves}


# MODO TREINO
def generate_random_position():
    """Gera uma posição de treino aleatória usando Stockfish."""
    stockfish.set_position([])  # Começa do início
    for _ in range(random.randint(10, 30)):
        move = stockfish.get_best_move()
        if not move:
            break
        stockfish.make_moves_from_current_position([move])
    return stockfish.get_fen_position()

@app.get("/generate_training_position/",tags=['TRAINING'])
def generate_training_position():
    """Gera uma posição aleatória de treino."""
    fen = generate_random_position()
    return {"training_position": fen}

@app.post("/get_best_move_for_training/",tags=['TRAINING'])
def get_best_move_for_training(fen: str):
    """Retorna a melhor jogada para uma posição de treino e explica o motivo."""
    stockfish.set_fen_position(fen)
    best_move = stockfish.get_best_move()
    eval_info = stockfish.get_evaluation()
    
    explanation = """Essa é a melhor jogada porque melhora sua posição estrategicamente."""
    if eval_info["type"] == "mate":
        explanation = "Essa jogada leva ao xeque-mate!"
    elif eval_info["value"] > 100:
        explanation = "Essa jogada garante uma vantagem sólida."
    elif eval_info["value"] < -100:
        explanation = "Essa jogada pode ser arriscada!"
    
    return {"best_move": best_move, "explanation": explanation, "board": stockfish.get_board_visual()}

@app.post("/evaluate_training_move/",tags=['TRAINING'])
def evaluate_training_move(fen: str, move: str):
    """Avalia se o movimento do usuário foi bom e explica o impacto."""
    stockfish.set_fen_position(fen)
    
    if not stockfish.is_move_correct(move):
        return {"message": "Movimento inválido!", "evaluation": "Erro"}
    
    eval_before = stockfish.get_evaluation()
    stockfish.make_moves_from_current_position([move])
    eval_after = stockfish.get_evaluation()
    
    eval_diff = eval_after["value"] - eval_before["value"]
    
    classification = "Neutra"
    if eval_diff > 50:
        classification = "Boa jogada!"
    elif eval_diff < -50:
        classification = "Movimento ruim!"
    
    return {"move": move, "classification": classification, "board": stockfish.get_board_visual()}


# ROTAS A SEREM USADAS AO PENSAR EM INTEGRAR COM O ROBO
@app.get("/get_next_move/",tags=['ROBOT'])
def get_next_move():
    """Retorna o próximo movimento sugerido pelo Stockfish sem executar."""
    best_move = stockfish.get_best_move()
    if not best_move:
        raise HTTPException(status_code=400, detail="Nenhuma jogada disponível!")
    return {"best_move": best_move}

@app.post("/confirm_robot_move/",tags=['ROBOT'])
def confirm_robot_move(move: str):
    """Confirma que o robô realizou a jogada."""
    global game_moves
    if not stockfish.is_move_correct(move):
        raise HTTPException(status_code=400, detail="Movimento inválido!")
    
    game_moves.append(move)
    stockfish.set_position(game_moves)
    return {"message": "Jogada do robô confirmada!", "board": stockfish.get_board_visual()}

@app.get("/game_status/",tags=['ROBOT'])
def game_status():
    """Retorna o status atual do jogo."""
    evaluation = stockfish.get_evaluation()
    return {
        "moves": game_moves,
        "evaluation": evaluation,
        "board": stockfish.get_board_visual()
    }

@app.post("/force_robot_move/",tags=['ROBOT'])
def force_robot_move():
    """Força o robô a fazer um movimento imediatamente."""
    global game_moves
    best_move = stockfish.get_best_move()
    if not best_move:
        raise HTTPException(status_code=400, detail="Nenhuma jogada disponível!")
    
    game_moves.append(best_move)
    stockfish.set_position(game_moves)
    return {"message": "Movimento do robô executado!", "move": best_move, "board": stockfish.get_board_visual()}

# TESTE DE MIGRATIONS COM SQLITE
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/items/", tags=['DB'])
def read_items(db: Session = Depends(get_db)):
    return db.query(Item).all()

@app.post("/items/", tags=['DB'])
def create_item(name: str, description: str, db: Session = Depends(get_db)):
    new_item = Item(name=name, description=description)
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item
