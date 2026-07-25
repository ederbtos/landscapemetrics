"""
Rota de gerenciamento de credenciais do Earth Engine
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import credentials as creds_db

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


class CredentialsPayload(BaseModel):
    service_account_json: str


@router.get("/")
def get_credentials_status(current_user: str = Depends(get_current_user)):
    creds = creds_db.get_credentials(current_user)

    return {
        "has_credentials": creds is not None,
        "client_email": creds.get("client_email") if creds else None,
        "project_id": creds.get("project_id") if creds else None,
    }


@router.post("/")
def save_credentials(
    payload: CredentialsPayload, current_user: str = Depends(get_current_user)
):

    import json
    try:
        parsed = json.loads(payload.service_account_json)
        if "type" not in parsed or parsed.get("type") != "service_account":
            raise ValueError("O JSON fornecido não é de uma conta de serviço válida do GCP.")
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"JSON de credenciais inválido: {err}",
        )

    creds_db.save_credentials(current_user, parsed)
    return {"message": "Credenciais salvas com sucesso!", "client_email": parsed.get("client_email")}
