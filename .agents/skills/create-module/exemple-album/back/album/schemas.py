from pydantic import BaseModel, ConfigDict
from typing import Optional

class AlbumBase(BaseModel):
    code: str
    titre: str
    auteur: str
    annee: Optional[int] = None
    nombre_pistes: Optional[int] = None
    duree: Optional[int] = None

class AlbumCreate(AlbumBase):
    pass

class AlbumUpdate(BaseModel):
    code: Optional[str] = None
    titre: Optional[str] = None
    auteur: Optional[str] = None
    annee: Optional[int] = None
    nombre_pistes: Optional[int] = None
    duree: Optional[int] = None

class Album(AlbumBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
