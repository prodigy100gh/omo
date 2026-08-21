import time
import requests
from django.core.management.base import BaseCommand
from movie.models import Movie
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '기존 DB 영화들의 추천작 정보만 초고속으로 업데이트합니다.'

    def handle(self, *args, **options):
        load_dotenv() # .env 파일 읽기
        API_KEY = os.getenv("TMDB_API_KEY") # 파일에서 키를 안전하게 불러옴
        
        # 1. 우리 DB에 있는 모든 영화 가져오기
        movies = Movie.objects.all()
        total_movies = movies.count()
        
        self.stdout.write(self.style.WARNING(f"🚀 총 {total_movies}개 영화의 '추천작 정보'만 단독 업데이트를 시작합니다..."))
        
        # 💡 [속도 향상 핵심 1] Session 객체를 쓰면 매번 구글(TMDB) 문을 열고 닫지 않고 열어둔 채로 통신해서 엄청나게 빠릅니다.
        session = requests.Session() 
        updated_movies = []
        
        start_time = time.time()
        
        for idx, movie in enumerate(movies, 1):
            # 💡 [속도 향상 핵심 2] 무거운 풀옵션 대신, 딱 '추천 영화'만 주는 가벼운 API 주소로 호출합니다.
            url = f"https://api.themoviedb.org/3/movie/{movie.id}/recommendations?api_key={API_KEY}&language=ko-KR"
            
            try:
                res = session.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    recommended_movies = []
                    
                    for rec in data.get('results', [])[:5]:
                        rec_poster = rec.get('poster_path')
                        rec_country = ""
                        if rec.get('origin_country'):
                            rec_country = self.get_country_kr_from_code(rec.get('origin_country')[0])
                        
                        recommended_movies.append({
                            "title": rec.get('title', ''),
                            "poster_url": f"https://image.tmdb.org/t/p/w185{rec_poster}" if rec_poster else "",
                            "release_date": rec.get('release_date', '')[:4],
                            "rating": round(rec.get('vote_average', 0.0), 1),
                            "vote_count": rec.get('vote_count', 0),
                            "country": rec_country,
                            "genre": "정보 없음"
                        })
                        
                    # 영화 객체에 새 데이터 덮어쓰기 준비
                    movie.tmdb_recommended_movies = recommended_movies
                    updated_movies.append(movie)
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"에러 발생 (ID {movie.id}): {e}"))
                time.sleep(1) # 에러 나면 잠깐 휴식
                
            # 💡 [속도 향상 핵심 3] 100개씩 모아서 DB에 한 방에 덮어씁니다 (Bulk Update)
            if len(updated_movies) >= 100:
                Movie.objects.bulk_update(updated_movies, ['tmdb_recommended_movies'])
                elapsed_str = self.format_time(time.time() - start_time)
                self.stdout.write(f"  ↳ {idx}/{total_movies} 완료... (진행시간: {elapsed_str})")
                updated_movies.clear() # 처리한 건 비우고 다시 100개 채우기
                
        # 100개 단위로 묶이지 못하고 남은 자투리 영화들 마저 업데이트
        if updated_movies:
            Movie.objects.bulk_update(updated_movies, ['tmdb_recommended_movies'])
            
        final_time = self.format_time(time.time() - start_time)
        self.stdout.write(self.style.SUCCESS(f"\n🎉 단독 업데이트 완벽하게 종료! (총 소요시간: {final_time})"))

    def get_country_kr_from_code(self, code):
        """국가 코드 한글 변환"""
        if not code: return "정보 없음"
        code_map = {
            "KR": "한국", "US": "미국", "JP": "일본", "CN": "중국", "HK": "홍콩", "TW": "대만",
            "GB": "영국", "FR": "프랑스", "DE": "독일", "IT": "이탈리아", "ES": "스페인", "IN": "인도",
            "CA": "캐나다", "AU": "호주", "RU": "러시아", "BR": "브라질", "MX": "멕시코"
            # 필요하다면 기존 스크립트에 있던 수많은 국가 코드를 여기에 그대로 복사해 넣으셔도 됩니다.
        }
        return code_map.get(code.upper(), f"기타({code.upper()})")

    def format_time(self, seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}분 {secs}초"