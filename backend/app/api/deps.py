"""
Descrição da funcionalidade
---------------------------
Dependências compartilhadas do FastAPI — o gate de login vira uma
`Depends(get_current_user)` reutilizável em toda rota autenticada, lendo o
access token do header `Authorization: Bearer`.
"""
from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.core.security import decode_access_token


def get_current_user(authorization: str | None = Header(default=None)) -> str:
    # --- BYPASS TEMPORÁRIO (remover depois — pedido do usuário 2026-07-30 para
    # rodar cálculos reais sem a fricção do login enquanto isso). Só ativa se
    # `dev_auth_bypass_email` estiver setado em backend/.env; ausente por
    # padrão, então isso não afeta ninguém que não configure explicitamente.
    bypass_email = get_settings().dev_auth_bypass_email
    if bypass_email:
        return bypass_email
    # --- fim do bypass ---

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado.")
    token = authorization.removeprefix("Bearer ").strip()
    email = decode_access_token(token)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
    return email
