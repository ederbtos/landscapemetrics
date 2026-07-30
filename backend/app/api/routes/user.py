"""
Rotas para Configurações e Preferências Individualizadas do Usuário (Escritório Virtual)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import user_settings as user_settings_db

router = APIRouter(prefix="/api/user", tags=["user"])


class UserSettingsPayload(BaseModel):
    default_buffer_dist: Optional[int] = 5000
    default_data_source: Optional[str] = "mapbiomas"
    default_uf: Optional[str] = "GO"
    selected_metrics: Optional[List[str]] = [
        "proportion_of_landscape",
        "number_of_patches",
        "edge_density",
        "shannon_diversity_index",
    ]


@router.get("/settings")
def get_settings(current_user: str = Depends(get_current_user)):
    """Retorna as configurações e preferências individualizadas do usuário logado."""
    return user_settings_db.get_user_settings(current_user)


@router.post("/settings")
def save_settings(
    payload: UserSettingsPayload, current_user: str = Depends(get_current_user)
):
    """Salva/atualiza as configurações e preferências individualizadas do usuário logado."""
    settings_dict = payload.model_dump()
    user_settings_db.save_user_settings(current_user, settings_dict)
    return {"message": "Configurações individualizadas salvas com sucesso!", "settings": settings_dict}
