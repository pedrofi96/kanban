from django.apps import AppConfig


class KanbanConfig(AppConfig):
    name = 'kanban'

    def ready(self):
        # Inscreve o kanban no sinal de transferência do app usuarios.
        from usuarios.signals import usuario_transferido

        from .services import remover_de_todos_os_quadros

        def ao_transferir(sender, usuario, andar_origem, ator, **kwargs):
            remover_de_todos_os_quadros(usuario, ator, motivo="mudou de andar")

        usuario_transferido.connect(ao_transferir, dispatch_uid="kanban_ao_transferir")
