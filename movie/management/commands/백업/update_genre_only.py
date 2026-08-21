import time
import requests
from django.core.management.base import BaseCommand
from movie.models import Movie
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '기존 추천작 데이터에 장르(genre)만 한글로 번역하여 초고속으로 추가합니다.'

    def handle(self, *args, **options):
        load_dotenv() # .env 파일 읽기
        API_KEY = os.getenv("TMDB_API_KEY") # 파일에서 키를 안전하게 불러옴
        
        # 💡 추천작이 비어있는 영화는 건너뛰기 (시간 단축)
        movies = Movie.objects.exclude(tmdb_recommended_movies__isnull=True).exclude(tmdb_recommended_movies__exact=[])
        total_movies = movies.count()
        
        self.stdout.write(self.style.WARNING(f"🚀 총 {total_movies}개 영화의 추천작 '장르' 단독 주입을 시작합니다..."))
        
        session = requests.Session() 
        updated_movies = []
        start_time = time.time()
        
        for idx, movie in enumerate(movies, 1):
            url = f"https://api.themoviedb.org/3/movie/{movie.id}/recommendations?api_key={API_KEY}&language=ko-KR"
            
            try:
                res = session.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    
                    # 💡 API에서 받은 '장르 숫자 암호'를 즉시 한글로 번역해서 딕셔너리로 준비합니다.
                    # 예: {"인셉션": "SF, 액션, 스릴러"}
                    genre_map = {}
                    for rec in data.get('results', []):
                        genre_map[rec.get('title')] = self.get_genre_kr_from_ids(rec.get('genre_ids', []))
                        
                    # 기존 DB에 있던 추천작 데이터 (방금 넣은 평가자 수도 안전하게 보관되어 있음)
                    current_recs = movie.tmdb_recommended_movies
                    is_modified = False
                    
                    # 💡 기존 데이터는 건드리지 않고 'genre' 필드만 한글로 갈아 끼웁니다.
                    for my_rec in current_recs:
                        title = my_rec.get('title')
                        if title in genre_map:
                            my_rec['genre'] = genre_map[title]
                            is_modified = True
                            
                    # 수정된 내용이 있을 때만 업데이트 리스트에 추가합니다.
                    if is_modified:
                        movie.tmdb_recommended_movies = current_recs
                        updated_movies.append(movie)
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"에러 발생 (ID {movie.id}): {e}"))
                time.sleep(1)
                
            # 100개씩 모아서 DB에 한 방에 덮어씁니다 (Bulk Update)
            if len(updated_movies) >= 100:
                Movie.objects.bulk_update(updated_movies, ['tmdb_recommended_movies'])
                elapsed_str = self.format_time(time.time() - start_time)
                self.stdout.write(f"  ↳ {idx}/{total_movies} 완료... (진행시간: {elapsed_str})")
                updated_movies.clear() 
                
        # 100개 단위로 묶이지 못하고 남은 영화들 마저 업데이트
        if updated_movies:
            Movie.objects.bulk_update(updated_movies, ['tmdb_recommended_movies'])
            
        final_time = self.format_time(time.time() - start_time)
        self.stdout.write(self.style.SUCCESS(f"\n🎉 장르 한글 번역 주입 완벽하게 종료! (총 소요시간: {final_time})"))

    def get_genre_kr_from_ids(self, genre_ids):
        """TMDB 장르 숫자 ID를 한글 장르명으로 변환"""
        if not genre_ids:
            return "정보 없음"
            
        # TMDB 공식 영화 장르 ID 매핑 테이블 (19개 완전판)
        genre_map = {
            28: "액션", 12: "모험", 16: "애니메이션", 35: "코미디", 80: "범죄",
            99: "다큐멘터리", 18: "드라마", 10751: "가족", 14: "판타지", 36: "역사",
            27: "공포", 10402: "음악", 9648: "미스터리", 10749: "로맨스", 878: "SF",
            10770: "TV 영화", 53: "스릴러", 10752: "전쟁", 37: "서부"
        }
        
        # 숫자를 한글로 바꾸고, 있는 것들만 모아서 쉼표로 연결 (예: "SF, 액션")
        genres = [genre_map.get(g_id) for g_id in genre_ids if genre_map.get(g_id)]
        return ", ".join(genres) if genres else "정보 없음"

    def format_time(self, seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}분 {secs}초"