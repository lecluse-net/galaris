from sqlalchemy import Column, Integer, String
from core.database import Base, HistoryMixin

class Album(HistoryMixin, Base):
    __tablename__ = "albums"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    titre = Column(String, nullable=False)
    auteur = Column(String, nullable=False)
    annee = Column(Integer, nullable=True)
    nombre_pistes = Column(Integer, nullable=True)
    duree = Column(Integer, nullable=True) # Durée en secondes
