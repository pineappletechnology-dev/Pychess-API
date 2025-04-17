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

def createResetToken(email: str):
    """ Gera um token JWT para redefinição de senha """
    expire = datetime.utcnow() + timedelta(minutes=30)
    data = {"sub": email, "exp": expire}
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def sendResetEmail(email: str, token: str):
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

def getUserByFilter(filters: dict, db: Session = Depends(get_db)):
    """
    Retrieve a user from the database based on specified filter criteria.

    Args:
        filters (dict): A dictionary containing filter criteria as key-value pairs.
                        The keys should correspond to attributes of the User model.
        db (Session, optional): The database session dependency. Defaults to Depends(get_db).

    Returns:
        User: The first user object that matches the filter criteria, or None if no match is found.

    Example:
        # Example usage
        filters = {"username": "john_doe", "email": "john@example.com"}
        user = getUserByFilter(filters, db)
        if user:
            print(f"User found: {user.username}")
        else:
            print("No user found.")
    """
    query = db.query(User)
    for key, value in filters.items():
        if hasattr(User, key):
            query = query.filter(getattr(User, key) == value)
    return query.first()

def getUserById(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()

def createUser(username:str, password:str, email:str, db: Session = Depends(get_db)):
    
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = bcrypt.hash(password)

    new_user = User(username=username, password=hashed_password, email=email)
    db.add(new_user)
    db.commit()

    return new_user

def login(username: str, password: str, SECRET_KEY, ALGORITHM, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not bcrypt.verify(password, user.password):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    # Gerar token JWT
    expiration = datetime.utcnow() + timedelta(hours=1)
    token = jwt.encode({"id": user.id, "exp": expiration}, str(SECRET_KEY), algorithm=ALGORITHM)

    return token

def getUsers(db: Session = Depends(get_db)):
    return db.query(User).order_by(desc(User.rating)).all()

def forgotPassword(email: str, db: Session = Depends(get_db)):
    """ Verifica se o e-mail existe e envia um link de recuperação """
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="E-mail não encontrado.")
    
    # Gerar token de redefinição de senha
    reset_token = createResetToken(email)
    
    # Enviar e-mail com link
    sendResetEmail(email, reset_token)
    
    return {"message": "E-mail de redefinição de senha enviado!"}
