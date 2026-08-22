import os
from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = '쪼개진 영화/TV 데이터를 순차적으로 로드합니다.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("🚀 데이터 순차 로딩 시작!"))

        # 영화 파일 18개
        for i in range(1, 19):
            filename = f"movie_data_part_{i:02d}.json"
            self.stdout.write(f"📦 [{filename}] 로드 시작...")
            try:
                call_command('loaddata', filename)
                self.stdout.write(self.style.SUCCESS(f"✅ [{filename}] 완료!"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"❌ [{filename}] 에러: {e}"))

        # TV 파일 8개
        for i in range(1, 9):
            filename = f"tv_data_part_{i:02d}.json"
            self.stdout.write(f"📦 [{filename}] 로드 시작...")
            try:
                call_command('loaddata', filename)
                self.stdout.write(self.style.SUCCESS(f"✅ [{filename}] 완료!"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"❌ [{filename}] 에러: {e}"))

        self.stdout.write(self.style.SUCCESS("🎉 모든 데이터 로딩 완료!"))