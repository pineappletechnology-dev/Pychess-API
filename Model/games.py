from sqlalchemy import Column, ForeignKey, Integer, Boolean
from sqlalchemy.orm import relationship
from database.database import Base

class Games(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    player_victory = Column(Boolean, index=True)

    users = relationship('users', back_populates='games')


    