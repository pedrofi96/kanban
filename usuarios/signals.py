"""
Sinais próprios do app usuarios.

O app `usuarios` não conhece o `kanban`. Quando alguém muda de andar,
ele só "avisa" por este sinal; quem precisa reagir (o kanban, que tira
a pessoa dos projetos) se inscreve nele em kanban/apps.py.
"""

from django.dispatch import Signal

# Enviado com: usuario, andar_origem, ator
usuario_transferido = Signal()
