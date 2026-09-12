"""iafood — infraestructura de IA (Fase 5, sección 10 de la especificación).

Este paquete es deliberadamente solo la infraestructura compartida:
credencial (`client.py`), límites de uso (`limits.py`) y el cliente del
Claude Agent SDK (`agent.py`). La anonimización, las herramientas de
function calling, los prompts y el validador de cada flujo concreto
(generación de dietas, chat, etc.) se añaden fase a fase, uno a la vez,
cuando ese flujo se construye — no se scaffoldan por adelantado.
"""
