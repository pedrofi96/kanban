from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import permissoes
from .models import Quadro

def grupo_do_quadro(quadro_id):
    return f"quadro_{quadro_id}"

class QuadroConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        self.grupo= None
        usuario = self.scope["user"]
        quadro_id = self.scope["url_route"]["kwargs"]["quadro_id"]

        if not await self.pode_ver(usuario, quadro_id):
            await self.close()
            return

        self.grupo=grupo_do_quadro(quadro_id)
        await self.channel_layer.group_add(self.grupo, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.grupo:
            await self.channel_layer.group_discard(self.grupo, self.channel_name)

    async def receive_json(self, content, **kwargs):
        """O navegador não manda nada por aqui: as mudanças vão pela API."""

    async def quadro_mudou(self, evento):
        await self.send_json({"tipo": "quadro_mudou", "origem":evento.get("origem")})

    @database_sync_to_async
    def pode_ver(self, usuario, quadro_id):
        if not usuario.is_authenticated:
            return False
        quadro = Quadro.objects.filter(pk=quadro_id).first()
        return quadro is not None and permissoes.pode_ver_quadro(usuario, quadro)

