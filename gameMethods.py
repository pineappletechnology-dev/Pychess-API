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
import dbMethods

# Lista global para armazenar até 3 últimas partidas
game_history = []

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH")

# Inicializa o motor Stockfish
stockfish = Stockfish(STOCKFISH_PATH)
stockfish.set_skill_level(10)  # Ajuste o nível de habilidade (0-20)
stockfish.set_depth(15)  # Profundidade de busca

def fenToMatrix(fen):
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

def setStockfishDifficultyLevel(level: str):
    difficulty_settings = {
        "muito_baixa": {"skill": 1, "depth": 2, "rating": 150},
        "baixa": {"skill": 2, "depth": 4, "rating": 300},
        "media": {"skill": 5, "depth": 8, "rating": 600},
        "dificil": {"skill": 10, "depth": 14, "rating": 1200},
        "extremo": {"skill": 20, "depth": 22, "rating": "MAX"}
    }

    level = level.lower()
    
    if level not in difficulty_settings:
        # raise HTTPException(status_code=400, detail="Nível inválido! Escolha entre: muito_baixa, baixa, media, dificil, extremo.")
        return False

    settings = difficulty_settings[level]

    stockfish.set_skill_level(settings["skill"])
    stockfish.set_depth(settings["depth"])

    return {
        "message": f"Dificuldade ajustada para '{level}'",
        "skill_level": settings["skill"],
        "depth": settings["depth"],
        "rating": settings["rating"]
    }


def verifyExistingGame(db: Session = Depends(get_db)):
    """
    Verifica se o usuário já possui uma partida ativa.

    Args:
        user_id (int): ID do usuário a ser verificado.
        db (Session, optional): A sessão do banco de dados. Padrão é Depends(get_db).

    Returns:
        Game: A partida ativa do usuário, se existir.
    """
    game = db.query(Game).filter(Game.player_win == 0).first()
    return game

def startNewGame(user_id: int, db: Session = Depends(get_db)):
    """
    Inicia uma nova partida para o usuário.

    Args:
        db (Session, optional): A sessão do banco de dados. Padrão é Depends(get_db).

    Returns:
        Game: O objeto da nova partida criada.
    """
     # Criar um novo jogo
    new_game = Game(user_id=user_id)
    db.add(new_game)
    db.commit()
    db.refresh(new_game)

    # Iniciar posição no Stockfish
    stockfish.set_position([])
    
    return new_game

def loadGame(game_id: int, db: Session = Depends(get_db)):
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

def getGameState(game_id: int, move_number: int, db: Session = Depends(get_db)):
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

def getGameBoard(db: Session = Depends(get_db)):
    """ Retorna a visualização do tabuleiro baseado no último estado salvo no banco. """

    # Obtém o último jogo ativo (onde player_win == 0)
    game = db.query(Game).filter(Game.player_win == 0).order_by(Game.id.desc()).first()
    if not game:
        raise HTTPException(status_code=404, detail="Nenhum jogo ativo encontrado.")

    # Obtém o último estado do tabuleiro salvo no banco (última jogada)
    last_move = db.query(Move.board_string).filter(Move.game_id == game.id).order_by(Move.id.desc()).first()
    if not last_move:
        raise HTTPException(status_code=404, detail="Nenhuma jogada encontrada para este jogo.")

    # Define a posição do Stockfish com base no último FEN salvo
    stockfish.set_fen_position(last_move.board_string)

    # Obtém o tabuleiro no formato visual do Stockfish
    board_visual = stockfish.get_board_visual().split("\n")

    return board_visual

def playGame(move: str, db: Session = Depends(get_db)):
    """ O usuário joga, e o Stockfish responde com a melhor jogada, verificando capturas. """

    # Verifica se existe um jogo ativo
    game = db.query(Game).filter(Game.player_win == 0).first()
    if not game:
        raise HTTPException(status_code=400, detail="Nenhum jogo ativo encontrado!")

    # Obtém os movimentos já registrados no banco para este jogo
    game_moves = db.query(Move.move).filter(Move.game_id == game.id).all()
    game_moves = [m.move for m in game_moves]  # Transformando em lista de strings

    # Obtém o estado do tabuleiro antes da jogada do usuário
    board_before = stockfish.get_fen_position()

    # Verifica se o movimento do jogador é válido
    if not stockfish.is_move_correct(move):
        raise HTTPException(status_code=400, detail="Movimento do jogador inválido!")
    
    # Se a posição não mudou, significa que o movimento foi inválido
    # if stockfish.get_fen_position() == board_before:
    #     raise HTTPException(status_code=400, detail="Movimento do jogador inválido!")

    # Adiciona a jogada do jogador
    game_moves.append(move)
    stockfish.set_position(game_moves)
    
    # Obtém o estado do tabuleiro depois da jogada do jogador
    board_after = stockfish.get_fen_position()

    # Converte FEN para matriz 8x8 antes e depois do movimento
    board_matrix_before = fenToMatrix(board_before)
    board_matrix_after = fenToMatrix(board_after)

    # Verifica se houve captura pelo jogador
    captured_piece_position = None
    captured_piece = None
    moved_piece = None
    from_square, to_square = move[:2], move[2:]  # Exemplo: "e2e4" -> "e2" e "e4"

    row_to, col_to = 8 - int(to_square[1]), ord(to_square[0]) - ord('a')

    if board_matrix_before[row_to][col_to] != "." and board_matrix_after[row_to][col_to] != board_matrix_before[row_to][col_to]:
        captured_piece_position = to_square
        captured_piece = board_matrix_before[row_to][col_to]
        moved_piece = board_matrix_after[row_to][col_to]

    # Análise da jogada
    analysis = analyzeMove(move, db)
    classification = analysis["classification"]

    # Salva o movimento do jogador no banco de dados
    new_move = Move(
        is_player=True,
        move=move,
        board_string=board_after,
        mv_quality=classification,
        game_id=game.id,
    )
    db.add(new_move)
    db.commit()

    evaluation = stockfish.get_evaluation()

    # Verifica xeque-mate após o movimento do jogador
    if evaluation['type'] == 'mate':
        game.player_win = 1  # Brancas vencem
        db.commit()

        rating(game.user_id)

        return {
            "message": "Xeque-mate! Brancas venceram!",
            "player_move": move,
            "player_capture": captured_piece_position,
            "captured_piece": captured_piece,
            "moved_piece": moved_piece,
            "stockfish_move": None,
            "stockfish_capture": None,
            "stockfish_captured_piece": None,
            "stockfish_moved_piece": None,
            "board": stockfish.get_board_visual()
        }

    # Stockfish responde com o melhor movimento
    best_move = stockfish.get_best_move()

    if not best_move or not stockfish.is_move_correct(best_move):
        raise HTTPException(status_code=400, detail="Movimento inválido gerado pelo Stockfish!")

    captured_piece_position_stockfish = None
    captured_piece_stockfish = None
    moved_piece_stockfish = None

    if best_move:
        # Obtém o estado do tabuleiro antes da jogada do Stockfish
        board_before_stockfish = stockfish.get_fen_position()

        game_moves.append(best_move)
        stockfish.set_position(game_moves)

        # Obtém o estado do tabuleiro depois da jogada do Stockfish
        board_after_stockfish = stockfish.get_fen_position()

        # Converte FEN para matriz 8x8 antes e depois do movimento do Stockfish
        board_matrix_before_sf = fenToMatrix(board_before_stockfish)
        board_matrix_after_sf = fenToMatrix(board_after_stockfish)

        # Verifica se houve captura pelo Stockfish
        from_square_sf, to_square_sf = best_move[:2], best_move[2:]

        row_to_sf, col_to_sf = 8 - int(to_square_sf[1]), ord(to_square_sf[0]) - ord('a')

        if board_matrix_before_sf[row_to_sf][col_to_sf] != "." and board_matrix_after_sf[row_to_sf][col_to_sf] != board_matrix_before_sf[row_to_sf][col_to_sf]:
            captured_piece_position_stockfish = to_square_sf
            captured_piece_stockfish = board_matrix_before_sf[row_to_sf][col_to_sf]
            moved_piece_stockfish = board_matrix_after_sf[row_to_sf][col_to_sf]

        # Salva o movimento do Stockfish no banco de dados
        stockfish_move = Move(
            is_player=False,
            move=best_move,
            board_string=board_after_stockfish,
            mv_quality=None,
            game_id=game.id,
        )
        db.add(stockfish_move)
        db.commit()

        # Verifica xeque-mate após o movimento do Stockfish
        if evaluation['type'] == 'mate':
            game.player_win = 2  # Pretas vencem

            db.commit()

            rating(game.user_id)

            return {
                "message": "Xeque-mate! Pretas venceram!",
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
        
    return {
        captured_piece_position: captured_piece_position,
        best_move: best_move,
        captured_piece_position_stockfish: captured_piece_position_stockfish
        }

def analyzeMove(move: str, db: Session = Depends(get_db)):
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
        best_move: best_move,
        eval_before_score: eval_before_score,
        eval_after_score: eval_after_score,
        eval_best_score: eval_best_score,
        classification: classification,
    }