import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.core.management.base import BaseCommand
from dotenv import load_dotenv

# 💡 본인의 앱 이름으로 import 경로를 수정하세요!
from 앱이름.models import Movie, TvSeries 

class Command(BaseCommand):
    help = "기존 DB에 누락된 '언어' 정보를 벌크(Bulk) 업데이트 방식으로 초고속 크롤링합니다."

    def add_arguments(self, parser):
        parser.add_argument('--target', type=str, default='all', choices=['all', 'movie', 'tv'])

    LANGUAGE_MAP = {
        'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어(표준어)', 'cn': '중국어(광둥어)', 'yue': '광둥어', 
        'tw': '중국어(대만)', 'th': '태국어', 'id': '인도네시아어', 'vi': '베트남어', 'tl': '타갈로그어', 'ms': '말레이어',
        'fr': '프랑스어', 'es': '스페인어', 'de': '독일어', 'it': '이탈리아어', 'pt': '포르투갈어', 'ru': '러시아어', 
        'nl': '네덜란드어', 'pl': '폴란드어', 'uk': '우크라이나어', 'cs': '체코어', 'hu': '헝가리어', 'el': '그리스어', 
        'ro': '루마니아어', 'sv': '스웨덴어', 'da': '덴마크어', 'no': '노르웨이어', 'fi': '핀란드어',
        'ar': '아랍어', 'tr': '튀르키예어', 'he': '히브리어', 'fa': '페르시아어',
        'hi': '힌디어', 'ta': '타밀어', 'te': '텔루구어', 'ml': '말라얄람어',
    }

    def fetch_language(self, session, item, media_type, api_key):
        url = f"https://api.themoviedb.org/3/{media_type}/{item.tmdb_id}?api_key={api_key}&language=ko-KR"
        try:
            # 💡 타임아웃을 5초로 짧게 주어 먹통 방지
            response = session.get(url, timeout=5)
            if response.status_code == 200:
                lang_code = response.json().get('original_language', '')
                if lang_code:
                    return item, lang_code
            elif response.status_code == 429:
                # TMDB API 호출 제한에 걸리면 1초 휴식
                time.sleep(1) 
        except Exception:
            pass
        
        # 에러가 나거나 언어가 없는 경우 무한 루프에 빠지지 않도록 'N/A' 반환
        return item, "N/A" 

    def process_model(self, model_class, media_type, api_key, session):
        batch_size = 1000 # 💡 한 번에 처리할 묶음 개수 (수정 가능)
        total_updated = 0
        total_target = model_class.objects.filter(tmdb_original_language__isnull=True).count()

        if total_target == 0:
            return

        self.stdout.write(self.style.WARNING(f"\n🚀 [{model_class.__name__}] 총 {total_target:,}개 초고속 업데이트 시작..."))

        while True:
            # 1. 빈 언어 항목을 batch_size(1,000개) 만큼만 DB에서 꺼내옵니다.
            items = list(model_class.objects.filter(tmdb_original_language__isnull=True)[:batch_size])
            if not items:
                break # 더 이상 처리할 항목이 없으면 루프 탈출

            updated_items = []
            
            # 2. 40개의 쓰레드가 1,000개의 API를 미친 듯이 호출합니다.
            with ThreadPoolExecutor(max_workers=40) as executor:
                futures = {executor.submit(self.fetch_language, session, item, media_type, api_key): item for item in items}
                
                for future in as_completed(futures):
                    item, lang_code = future.result()
                    
                    if lang_code == "N/A":
                        item.tmdb_original_language = "확인불가" # 무한 루프 방지용 꼬리표
                    else:
                        item.tmdb_original_language = self.LANGUAGE_MAP.get(lang_code, lang_code.upper())
                    
                    updated_items.append(item)

            # 3. 🚀 핵심 기술 (벌크 업데이트): 1,000개의 수정사항을 DB에 단 1번의 쿼리로 밀어 넣습니다!
            if updated_items:
                model_class.objects.bulk_update(updated_items, ['tmdb_original_language'])
                total_updated += len(updated_items)
                
                self.stdout.write(self.style.SUCCESS(
                    f"✅ [{model_class.__name__}] 진행률: {total_updated:,} / {total_target:,} 완료"
                ))

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")
        target = options['target']

        if not API_KEY:
            self.stdout.write(self.style.ERROR("❌ TMDB_API_KEY가 설정되지 않았습니다."))
            return

        # 커넥션 풀을 사용하여 HTTP 연결 속도 최적화
        # 💡 변경: 원래 crawl.py에서 쓰셨던 강력한 재시도(Retry) 세션 이식
        session = requests.Session()
        # 429, 500번대 에러 발생 시 최대 3번까지 알아서 재시도합니다
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries))

        # Movie와 TvSeries를 순차적으로 초고속 처리
        if target in ['all', 'movie']:
            self.process_model(Movie, "movie", API_KEY, session)
        
        if target in ['all', 'tv']:
            self.process_model(TvSeries, "tv", API_KEY, session)

        self.stdout.write(self.style.SUCCESS("\n🎉 모든 언어 업데이트가 초고속으로 완료되었습니다!"))