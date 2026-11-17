
from django.urls import path
from . import consumers

websocket_urlpatterns = [
    # noinspection PyTypeChecker
    path("ws/quadros/<int:quadro_id>/", consumers.QuadroConsumer.as_asgi()),
]