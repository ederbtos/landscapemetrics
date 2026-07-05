# Documentação — Landscape Metrics Extractor

Fonte oficial de documentação técnica do sistema. Todo o conteúdo é derivado do código e da
configuração reais do repositório nesta revisão — nada aqui descreve funcionalidades planejadas
ou hipotéticas (para isso, ver [../ROADMAP.md](../ROADMAP.md)).

| # | Documento | Conteúdo |
| --- | --- | --- |
| 01 | [Visão geral](01_overview.md) | O que é, objetivo, público-alvo, funcionalidades principais |
| 02 | [Arquitetura](02_architecture.md) | Camadas, diagrama de componentes, tecnologias |
| 03 | [Design do sistema](03_system_design.md) | Componentes, comunicação entre módulos, decisões arquiteturais |
| 04 | [Banco de dados](04_database.md) | Modelagem, entidades, ERD |
| 05 | [API](05_api.md) | Por que não há API REST, contratos internos entre módulos |
| 06 | [Funcionalidades](06_features.md) | Lista completa de funcionalidades |
| 07 | [Fluxos de usuário](07_user_flows.md) | Fluxogramas dos principais fluxos |
| 08 | [Telas](08_ui_screens.md) | Telas, objetivo e ações de cada uma |
| 09 | [Regras de negócio](09_business_rules.md) | Regras, validações e restrições detalhadas |
| 10 | [Integrações](10_integrations.md) | Google Earth Engine, MapBiomas, Google OAuth |
| 11 | [Segurança](11_security.md) | Autenticação, autorização, boas práticas |
| 12 | [LGPD](12_lgpd_compliance.md) | Dados pessoais tratados, gaps de conformidade conhecidos |
| 13 | [Testes](13_testing.md) | Estratégia, estrutura e cobertura da suíte em `tests/` |
| 14 | [Deploy](14_deployment.md) | Como rodar local/Docker/produção, variáveis de ambiente |
| 15 | [Guia do desenvolvedor](15_dev_guide.md) | Onboarding, convenções, estrutura de pastas |
| 16 | [Troubleshooting](16_troubleshooting.md) | Problemas comuns e soluções |
| 17 | [Glossário](17_glossary.md) | Termos de negócio e técnicos |

## Por onde começar

- **Novo no projeto?** Leia 01 → 02 → 15, nessa ordem.
- **Vai mexer no pipeline de métricas?** Leia 03, 09 e a suíte de testes em 13 antes de editar
  `app.py`.
- **Vai fazer deploy?** Leia 14 e [../ROADMAP.md](../ROADMAP.md) (Fase 4).
- **Dúvida sobre um erro específico do app?** Vá direto ao 16.
