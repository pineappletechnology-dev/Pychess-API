from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database.database import SessionLocal, engine
from stockfish import Stockfish

from passlib.hash import bcrypt_sha256 as bcrypt
from database.database import get_db 
from Model.users import User

import math
import time
import math

app = FastAPI()

STOCKFISH_PATH = r"C:\Users\joao.silva\OneDrive - Allparts Componentes Ltda\Documentos\GitHub\Pychess-API\stockfish\stockfish-windows-x86-64-avx2.exe"

# Inicializa o motor Stockfish
stockfish = Stockfish(STOCKFISH_PATH)
stockfish.set_skill_level(10)  # Ajuste o nível de habilidade (0-20)
stockfish.set_depth(15)  # Profundidade de busca

# Variável para armazenar o histórico do jogo
game_moves = []
saved_games = {}

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

@app.get("/evaluate_position/", tags=['GAME'])
def evaluate_position():
    """ Avalia a posição do tabuleiro por 5 segundos, aumentando a profundidade da análise a cada segundo. """
    global game_moves
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

        time.sleep(1)  # Aguarda 1 segundo antes de aumentar a profundidade

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
def rating():
    """Avalia o jogo completo armazenado em game_moves e gera um rating baseado na performance do jogador."""
    global stockfish

    if not game_moves:
        raise HTTPException(status_code=400, detail="Nenhuma jogada registrada para avaliação.")

    base_rating = 0  # Rating inicial do jogador. Obs: Quando for ligar com o banco de dados será o rating do jogador
    rating = base_rating
    
    stockfish.set_position([])  # Reseta para o início da partida

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
            rating += 15  # Jogada perfeita
        elif eval_diff > 200:
            rating -= 50  # Erro grave (Blunder)
        elif eval_diff > 100:
            rating -= 20  # Jogada imprecisa
        elif eval_diff > 30:
            rating -= 5   # Pequeno erro
        else:
            rating += 5   # Jogada sólida

        # Falta 1 detalhe mas será implementado apenas quando tiver o banco finalizado, comparar o novo rating com o antigo e fazer a soma
        # sendo assim vamos estipular alguns valores para aumentar esse valor baseado na dificuldade e no desempenho do jogador

    return {
        "message": "Avaliação concluída!",
        "final_rating": max(0, rating),  # Evita rating negativo
        "moves_analyzed": len(game_moves)
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

@app.post("/login/", tags=['DB'])
def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not bcrypt.verify(password, user.password):
        raise HTTPException(status_code=400, detail="Invalid username or password")
    
    return {"message": "Login successful", "id": user.id}