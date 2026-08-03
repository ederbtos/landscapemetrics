import time
import re
import json
import logging
from typing import Dict, List, Any
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Logger estruturado para SIEM / ELK
logger = logging.getLogger("security.autonomous")
logger.setLevel(logging.INFO)
# Em produção, adicionar um FileHandler ou LogstashHandler em formato JSON
if not logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter('{"time": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": %(message)s}')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# Assinaturas conhecidas de LLM Prompt Injection (OWASP LLM01)
PROMPT_INJECTION_SIGNATURES = [
    r"(?i)\bignore\s+(all\s+)?(previous\s+)?instructions\b",
    r"(?i)\byou\s+are\s+now\b",
    r"(?i)\bdisregard\s+(all\s+)?(previous\s+)?\b",
    r"(?i)\bbypass\s+system\b",
    r"(?i)\bprint\s+your\s+prompt\b"
]

class AdaptiveRateLimiter:
    """Implementa UBA (User Behavior Analytics) simples baseado em janela deslizante."""
    def __init__(self, max_requests: int = 100, window_seconds: int = 60, block_time_seconds: int = 300):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.block_time_seconds = block_time_seconds
        # Estrutura: { ip_address: {"hits": [timestamps], "blocked_until": timestamp} }
        self.clients: Dict[str, Dict[str, Any]] = {}

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        
        if ip not in self.clients:
            self.clients[ip] = {"hits": [], "blocked_until": 0}
            
        client = self.clients[ip]
        
        if client["blocked_until"] > now:
            return False
            
        # Limpar timestamps fora da janela
        client["hits"] = [t for t in client["hits"] if now - t <= self.window_seconds]
        
        if len(client["hits"]) >= self.max_requests:
            client["blocked_until"] = now + self.block_time_seconds
            logger.warning(json.dumps({
                "event": "rate_limit_exceeded", 
                "ip": ip, 
                "msg": f"IP bloqueado por {self.block_time_seconds}s"
            }))
            return False
            
        client["hits"].append(now)
        return True


class AutonomousSecurityGuard(BaseHTTPMiddleware):
    def __init__(self, app, max_req_per_min: int = 60):
        super().__init__(app)
        self.limiter = AdaptiveRateLimiter(max_requests=max_req_per_min, window_seconds=60)
        self.injection_regexes = [re.compile(sig) for sig in PROMPT_INJECTION_SIGNATURES]

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # 1. Rate Limiting Autônomo
        if not self.limiter.is_allowed(ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests. Autonomous Security Guard blocked this IP due to anomalous behavior."}
            )

        # 2. IA Guardrails (Sanitização e Bloqueio de Prompt Injection)
        # Analisa parâmetros da query
        query_str = str(request.url.query)
        if self._contains_injection(query_str):
            logger.critical(json.dumps({"event": "prompt_injection_detected", "ip": ip, "target": "query"}))
            return JSONResponse(status_code=403, content={"detail": "Forbidden: Security policy violation (AI Guard)."})
        
        # Analisa corpo da requisição (se não for multipart form, pois é custoso ler o body aqui em streaming)
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    # Precisamos ler o body sem travar a requisição no FastAPI
                    body_bytes = await request.body()
                    if self._contains_injection(body_bytes.decode('utf-8', errors='ignore')):
                        logger.critical(json.dumps({"event": "prompt_injection_detected", "ip": ip, "target": "body"}))
                        return JSONResponse(status_code=403, content={"detail": "Forbidden: Security policy violation (AI Guard)."})
                    
                    # Como lemos o body, precisamos "injetar" de volta para o próximo middleware
                    async def receive():
                        return {"type": "http.request", "body": body_bytes}
                    request._receive = receive
                except Exception as e:
                    logger.error(json.dumps({"event": "security_body_read_error", "error": str(e)}))

        # Passar para o próximo middleware
        response = await call_next(request)

        # Omissão de Server Headers para evitar fingerprinting (Segurança em profundidade)
        if "server" in response.headers:
            del response.headers["server"]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        return response

    def _contains_injection(self, text: str) -> bool:
        if not text:
            return False
        for regex in self.injection_regexes:
            if regex.search(text):
                return True
        return False
