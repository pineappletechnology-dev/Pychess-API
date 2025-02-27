from sqlalchemy import Column, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import relationship
from database.database import Base

class Moves(Base):
    __tablename__ = "moves"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    is_player = Column(Boolean, index=True)
    move = Column(String, index=True)
    mv_quality = Column(String, index=True)
    game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE') , index=True, nullable=False)

    games = relationship('games', back_populates='moves')