from django.urls import path
from . import views

print("=" * 60)
print("▶ [디버그] 현재 Django가 읽은 views.py의 실제 경로:", views.__file__)
print("▶ [디버그] views.py 내부에서 인식된 함수 목록:", [f for f in dir(views) if not f.startswith('_')])
print("=" * 60)

urlpatterns = [
    path('', views.home, name='home'),
    path('movie/<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('rate/<int:movie_id>/', views.rate_movie, name='rate_movie'),
    path('mypage/', views.my_page, name='my_page'), 
    # -------------------------------------------------------------------
    # 🔥 [새로 추가] AI 추천 비동기 데이터를 전송해주는 API 주소
    # -------------------------------------------------------------------
    # 💡 [AI 추천 API] 홈페이지 상단 'AI 맞춤 영화 추천' 비동기 로딩용
    path('api/recommendations/', views.api_gemini_recommendations, name='api_gemini_recommendations'),
    
    # 💡 [AI TV 추천 API] 일관성 있는 완벽한 짝꿍!
    path('api/recommendations/tv/', views.api_gemini_tv_recommendations, name='api_gemini_tv_recommendations'),

    path('api/lazy-translate/', views.api_lazy_translate, name='api_lazy_translate'),
    path('api/youtube-reviews/<int:movie_id>/', views.api_youtube_reviews, name='api_youtube_reviews'),

    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('onboarding/', views.onboarding_view, name='onboarding'),
    path('onboarding/reset/', views.reset_ratings, name='reset_ratings'),
    path('movie/<int:movie_id>/watchlist/', views.toggle_watchlist, name='toggle_watchlist'),
    path('<int:movie_id>/reviews/', views.movie_reviews_all, name='movie_reviews_all'),

    path('tv/<int:series_id>/', views.tv_detail, name='tv_detail'),
    path('tv/<int:series_id>/rate/', views.rate_tv, name='rate_tv'),
    path('tv/<int:series_id>/reviews/', views.tv_reviews_all, name='tv_reviews_all',),
    path('tv/<int:series_id>/watchlist/',views.toggle_watchlist, name='toggle_tv_watchlist',),

    # 💡 AI 추천 전체 보기 전용 URL
    path('recommendations/more/', views.rec_more_movies_view, name='rec_more_movies'),
    path('recommendations/tv/more/', views.rec_more_tv_view, name='rec_more_tv'),

    path('all-list/', views.all_list, name='all_list'),

    # 💡 유튜브 예고편 자동 검색 API 주소 추가
    path('api/lazy-trailer/', views.api_lazy_trailer, name='api_lazy_trailer'),

    path('person/<int:person_id>/', views.person_detail, name='person_detail'),
    
    path('api/keyword-rec/', views.api_keyword_recommend, name='api_keyword_rec'),

    path('api/report_trailer/', views.api_report_trailer, name='api_report_trailer'),
]