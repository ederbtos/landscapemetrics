"""
Descrição da funcionalidade
---------------------------
Dependências compartilhadas do FastAPI — equivalente ao gate de login que
`main()` fazia no topo do script Streamlit (`auth.is_logged_in()` +
`st.stop()`). Aqui vira uma `Depends(get_current_user)` reutilizável em toda
rota autenticada, lendo o access token do header `Authorization: Bearer`.
"""
from fastapi import Header, HTTPException, status

from app.core.security import decode_access_token


def get_current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado.")
    token = authorization.removeprefix("Bearer ").strip()
    email = decode_access_token(token)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
    return email
