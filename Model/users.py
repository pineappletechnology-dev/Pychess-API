from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from database.database import Base

class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String, index=True)
    password = Column(String, index=True)
    wins = Column(Integer, index=True)
    losses = Column(Integer, index=True)
    total_games = Column(Integer, index=True)

    games = relationship('games', back_populates='users', cascade='all, delete-orphan')


    