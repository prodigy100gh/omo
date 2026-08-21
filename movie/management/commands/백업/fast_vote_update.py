import requests
import time
from django.core.management.base import BaseCommand
from django.db import transaction
from movie.models import TvSeries
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '기존 TV 시리즈의 seasons_data에 누락된 vote_count(투표수)만 빠르게 API로 가져와 업데이트합니다.'

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        self.stdout.write(self.style.WARNING("🔥 시즌 투표수(vote_count) 초고속 업데이트를 시작합니다..."))

        # 1. seasons_data가 존재하는 작품들만 가져옵니다.
        target_series = TvSeries.objects.exclude(seasons_data__isnull=True).exclude(seasons_data=[])
        total_count = target_series.count()

        if total_count == 0:
            self.stdout.write(self.style.ERROR("❌ 업데이트할 TV 시리즈 데이터가 없습니다."))
            return

        self.stdout.write(f"🎯 검사 및 업데이트 대상 TV 시리즈: 총 {total_count}개")

        updated_list = []
        batch_size = 500  # 500개씩 모아서 한방에 DB 저장 (속도 극대화)
        success_count = 0
        skip_count = 0

        for idx, series in enumerate(target_series, 1):
            # 💡 [스마트 스킵] 첫 번째 시즌 데이터에 이미 'vote_count'가 있는지 검사
            needs_update = False
            for s in series.seasons_data:
                if 'vote_count' not in s:
                    needs_update = True
                    break
            
            if not needs_update:
                skip_count += 1
                continue

            tmdb_id = series.id
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={API_KEY}&language=ko-KR"
            
            # 2. TMDB API 초고속 호출 (재시도 로직 포함)
            data = None
            while True:
                try:
                    # 💡 부가 정보(append_to_response) 없이 순수 기본 정보만 요청하여 응답 속도 극대화
                    res = requests.get(url, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        break
                    elif res.status_code == 404:
                        break
                    elif res.status_code == 429:
                        time.sleep(3)
                    else:
                        time.sleep(1)
                except Exception:
                    time.sleep(1)

            if not data:
                continue

            # 3. TMDB API에서 가져온 최신 시즌 데이터에서 vote_count만 추출하여 사전(Dict)으로 매핑
            # 예: { 1: 1523, 2: 840, 3: 450 } (시즌번호: 투표수)
            api_seasons = {s.get('season_number'): s.get('vote_count', 0) for s in data.get('seasons', [])}

            # 4. 내 DB의 seasons_data에 vote_count 쏙쏙 끼워 넣기
            for s in series.seasons_data:
                sn = s.get('season_number')
                s['vote_count'] = api_seasons.get(sn, 0)
            
            updated_list.append(series)
            success_count += 1

            # 진행 상황 출력 (100개마다)
            if idx % 100 == 0:
                self.stdout.write(self.style.HTTP_INFO(f"  ↳ {idx}/{total_count} 개 검사 완료 (업데이트: {success_count} / 스킵: {skip_count})"))

            # 5. 배치 사이즈(500개)만큼 차면 DB에 한 번에 덮어쓰기 (DB 부하 최소화)
            if len(updated_list) >= batch_size:
                TvSeries.objects.bulk_update(updated_list, ['seasons_data'])
                updated_list = []
                time.sleep(0.5)

        # 남은 찌꺼기 최종 업데이트
        if updated_list:
            TvSeries.objects.bulk_update(updated_list, ['seasons_data'])

        self.stdout.write(self.style.SUCCESS(f"\n🎉 작업 완료! 총 {success_count}개 작품의 시즌 투표수가 성공적으로 추가되었습니다. (이미 채워져서 스킵된 작품: {skip_count}개)"))