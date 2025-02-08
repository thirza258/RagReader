from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.GenerateChat.as_view(), name='chat'),
    path('file/', views.FileSubmit.as_view(), name='file'),
    path('clean/', views.CleanChatSystem.as_view(), name='clean'),
]