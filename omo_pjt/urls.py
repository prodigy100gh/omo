from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('movie.urls')),  # movie 앱의 urls.py를 바라보게 설정
]