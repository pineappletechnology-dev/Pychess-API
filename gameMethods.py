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