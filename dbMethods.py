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
