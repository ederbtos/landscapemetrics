# 01 — Visão Geral do Sistema

## O que é

**Landscape Metrics Extractor** é uma aplicação web (Streamlit) que extrai e calcula métricas de
paisagem — composição e configuração da cobertura do solo — para um ponto de interesse escolhido
pelo usuário, dentro de um raio (buffer) configurável em metros.

## Objetivo

Dar a pesquisadores e técnicos ambientais uma análise de paisagem pronta (área, número de manchas,
forma, proximidade entre manchas etc.) sem precisar programar diretamente contra o Google Earth
Engine ou a biblioteca PyLandStats.

## Problema que resolve

Calcular métricas de paisagem "na mão" exige: (1) acesso e conhecimento de scripting em Google
Earth Engine, (2) saber localizar e usar os assets corretos do MapBiomas, (3) conhecimento de
PyLandStats para o cálculo em si. O app encapsula essas três etapas atrás de uma interface visual:
o usuário desenha um ponto num mapa, escolhe um raio, e recebe uma tabela de métricas e um CSV para
download — sem escrever código.

## Público-alvo

- Pesquisadores e estudantes de ecologia de paisagem, geografia e áreas afins.
- Técnicos ambientais que precisam de uma análise rápida de uma área específica.
- Qualquer usuário com uma conta de serviço própria do Google Earth Engine (pré-requisito de
  acesso — ver [11_security.md](11_security.md)).

## Principais funcionalidades

| Funcionalidade | Descrição |
| --- | --- |
| Login | E-mail/senha (sempre disponível) ou Google OAuth (opcional, se configurado) |
| Credenciais por usuário | Cada usuário cadastra sua própria conta de serviço do Earth Engine |
| Seleção de ponto | Mapa interativo (desenho de marcador) + exportação/upload de GeoJSON |
| Fonte de dados | MapBiomas via Earth Engine **ou** GeoTIFF próprio enviado pelo usuário |
| Buffer configurável | Raio entre 1.000 m e 10.000 m ao redor do ponto |
| Cálculo de métricas | 12+ métricas de paisagem via PyLandStats, sob demanda (botão explícito) |
| Visualização | Mapa da área de interesse + gráfico das classes de cobertura do solo |
| Exportação | Download da tabela de métricas em CSV |

## O que o sistema **não** é

- Não é uma API REST nem um serviço multiusuário com processamento em fila — é um script
  Streamlit executado top-to-bottom a cada interação (ver [02_architecture.md](02_architecture.md)).
- Não gera nem exibe dados sintéticos/fictícios em caso de falha na extração real — o
  processamento é interrompido explicitamente (ver [09_business_rules.md](09_business_rules.md)).

## Estado do projeto

Ver [ROADMAP.md](../ROADMAP.md) na raiz do repositório para o progresso por fase (atualmente
93,75%, faltando apenas a execução da Fase 4 — deploy em produção).
