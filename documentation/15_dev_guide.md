# 15 — Guia para Desenvolvedores

## Onboarding rápido

1. Leia [01_overview.md](01_overview.md) e [02_architecture.md](02_architecture.md) primeiro.
2. Rode o app localmente (ver [14_deployment.md](14_deployment.md)) com uma conta de teste do
   Earth Engine antes de alterar qualquer coisa no pipeline de métricas.
3. Os três módulos (`app.py`, `auth.py`, `db.py`) têm um docstring de módulo no topo seguindo
   sempre a mesma estrutura — leia-o antes de mexer no arquivo (ver seção abaixo).

## Convenção de documentação no código

Todo módulo do projeto começa com um docstring estruturado nestas seções fixas:

```
Descrição da funcionalidade   -> o que o módulo resolve, em termos de negócio
Contexto técnico              -> como se encaixa na arquitetura, dependências
Regras de negócio             -> invariantes que o módulo garante
Pontos de atenção             -> riscos/limitações conhecidas, não óbvias pelo código
Melhorias sugeridas           -> (quando aplicável) o que faria sentido refatorar
```

Comentários inline seguem a mesma filosofia: explicam **por quê**, não **o quê** — ex.:
"Decisão de projeto: usa o endpoint `earthengine-highvolume` porque..." em vez de "Inicializa o
Earth Engine". Ao adicionar código novo, mantenha esse padrão: só comente o que não seria óbvio
para quem lê o código pela primeira vez.

## Padrões de código observados

- **Idioma**: comentários, docstrings e mensagens de UI em português; nomes de variáveis/funções
  em inglês/português misto, seguindo o que já existe no arquivo sendo editado.
- **Tratamento de erro**: nunca mascarar uma falha de extração de dados reais com um valor
  fabricado — propagar a exceção com uma mensagem que explique a causa provável (ver
  [09_business_rules.md](09_business_rules.md)). Isso é uma regra de negócio, não apenas estilo.
- **Streamlit rerun model**: qualquer estado que precise sobreviver a uma nova execução do script
  (ex.: resultado de um cálculo pesado) deve ir para `st.session_state`, nunca depender de uma
  variável local sobrevivendo entre interações.
- **Nomes de arquivo de upload**: nunca usar o nome original do arquivo como caminho em disco —
  gerar via `uuid.uuid4()` (ver `validate_file_upload`/`uploaded_file_to_gdf`).
- **Segredos**: sempre via `st.secrets`, nunca hardcoded; funções que dependem de um segredo
  devem levantar um erro claro (com o comando para gerá-lo) se ele estiver ausente — ver
  `auth._get_jwt_secret` e `db._get_fernet` como referência.

## Estrutura de pastas

```
.
├── app.py                      # UI principal + pipeline de métricas
├── auth.py                     # login, sessão, landing page
├── db.py                       # acesso a dados (SQLite)
├── requirements.txt            # dependências Python (única fonte de verdade de versões)
├── Dockerfile                  # imagem única, usada em dev e produção
├── docker-compose.yml          # stack local (sem HTTPS)
├── docker-compose.prod.yml     # stack de produção (+ Caddy/HTTPS)
├── Caddyfile.example           # modelo do proxy reverso
├── scripts/
│   ├── deploy.sh                # deploy de produção em um comando
│   └── backup-db.sh             # backup do SQLite
├── .streamlit/
│   ├── config.toml               # config do Streamlit (ex.: maxUploadSize)
│   └── secrets.toml.example      # modelo de segredos (nunca commitar o real)
├── documentation/               # esta documentação
├── tests/                       # suíte de testes (ver 13_testing.md)
├── data/                        # SQLite + backups (fora do Git)
├── README.md                    # visão geral + instalação, voltado a usuários finais
└── ROADMAP.md                   # progresso por fase, voltado ao acompanhamento do projeto
```

## Ao adicionar uma nova métrica ou classe de cobertura do solo

1. Atualize `metrics_names`/`metrics_traducao` em `app.py` (lista exibida no expander de
   detalhamento) se for uma métrica nova do PyLandStats.
2. Se for uma mudança de legenda (`legend_keys`), confirme contra a collection do MapBiomas
   realmente em uso — não há acoplamento automático entre a collection selecionada em runtime e
   esse dicionário (ver [09_business_rules.md](09_business_rules.md)).
3. Adicione/atualize o teste correspondente em `tests/` (ver [13_testing.md](13_testing.md)).

## Ao tocar em `auth.py` ou `db.py`

Esses dois módulos são o núcleo de segurança do sistema (senha, JWT, criptografia de credenciais).
Qualquer mudança deve preservar as garantias descritas em [11_security.md](11_security.md) — em
particular, nunca armazenar senha ou credencial do Earth Engine em texto puro.

## Antes de abrir um PR

- Rode a suíte de testes (`pytest tests/ -v`) — ver [13_testing.md](13_testing.md).
- Se a mudança afeta o pipeline principal (`app.py`), teste manualmente ao menos um fluxo completo
  local (login → credencial → ponto → cálculo → download), já que grande parte da UI não tem
  cobertura automatizada de E2E completa.
- Atualize [ROADMAP.md](../ROADMAP.md) se a mudança fechar ou abrir um item de fase.
