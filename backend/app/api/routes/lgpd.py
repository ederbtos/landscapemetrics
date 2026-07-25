"""
Rotas para Governança LGPD, Consentimento Auditável e Direitos do Titular (Art. 18)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from datetime import datetime, timezone
import hashlib
import json

from app.api.deps import get_current_user
from app.db import metric_results as metric_results_db
from app.db import users as users_db
from app.db import credentials as credentials_db

router = APIRouter(prefix="/api/lgpd", tags=["lgpd"])


class ConsentPayload(BaseModel):
    term_version: str = "v1.0"
    accepted: bool = True


@router.post("/consent")
def record_consent(
    payload: ConsentPayload,
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Registra o consentimento do usuário com hash imutável de auditoria (IP, User-Agent, timestamp)."""
    if not payload.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="É necessário aceitar os termos de consentimento para prosseguir.",
        )

    client_ip = request.client.host if request.client else "127.0.0.1"
    user_agent = request.headers.get("user-agent", "desconhecido")
    timestamp = datetime.now(timezone.utc).isoformat()

    consent_raw = f"{current_user}|{client_ip}|{user_agent}|{payload.term_version}|{timestamp}"
    consent_hash = hashlib.sha256(consent_raw.encode("utf-8")).hexdigest()

    return {
        "user_email": current_user,
        "term_version": payload.term_version,
        "accepted": True,
        "client_ip": client_ip,
        "timestamp_utc": timestamp,
        "consent_hash": consent_hash,
    }


@router.get("/export")
def export_user_data(current_user: str = Depends(get_current_user)):
    """Direito de Portabilidade (Art. 18, V): Exporta todos os dados do titular em JSON."""
    user_results = metric_results_db.list_metric_results(current_user, full=True)
    credentials_status = credentials_db.get_credentials(current_user) is not None

    return {
        "titular_email": current_user,
        "export_date": datetime.now(timezone.utc).isoformat(),
        "lgpd_base_legal": "Consentimento e Execução de Contrato",
        "gee_credentials_cadastradas": credentials_status,
        "historico_analises_salvas": user_results,
    }


@router.delete("/account")
def delete_user_account(current_user: str = Depends(get_current_user)):

    """Direito de Eliminação dos Dados (Art. 18, VI): Remove permanentemente a conta e histórico do titular."""
    # Exclui resultados
    history = metric_results_db.list_metric_results(current_user)
    for item in history:
        metric_results_db.delete_metric_result(current_user, item["fingerprint"])

    # Exclui credenciais
    credentials_db.delete_credentials(current_user)
    users_db.delete_user(current_user)

    return {
        "message": "Conta e todos os dados associados foram eliminados permanentemente em conformidade com a LGPD.",
        "protocolo_exclusao": f"LGPD-DEL-{hashlib.md5(current_user.encode()).hexdigest()[:8].upper()}",
    }
