def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries))

        for model_class, media_type in [(Movie, "movie"), (TvSeries, "tv")]:
            total_target = model_class.objects.count()
            self.stdout.write(self.style.WARNING(f"\n🚀 [{model_class.__name__}] {total_target:,}개 국가 정보 수리 시작..."))
            
            batch_size = 1000
            total_updated = 0
            
            # 💡 [최적화 핵심] Offset(건너뛰기) 대신 마지막 처리한 ID를 기억해서 그 다음부터 가져옴!
            last_id = 0 

            while True:
                # 마지막 ID보다 큰 애들 중 1,000개를 가져옵니다. (DB 조회 속도가 0.001초 컷으로 일정함)
                items = list(model_class.objects.filter(id__gt=last_id).order_by('id')[:batch_size])
                
                if not items:
                    break # 더 이상 가져올 데이터가 없으면 탈출!

                last_id = items[-1].id # 가져온 1,000개 중 가장 마지막 놈의 ID를 저장해둠
                updated_items = []

                with ThreadPoolExecutor(max_workers=40) as executor:
                    futures = {executor.submit(self.fetch_countries, session, item, media_type, API_KEY): item for item in items}
                    
                    for future in as_completed(futures):
                        result_item = future.result()
                        if result_item:
                            updated_items.append(result_item)

                if updated_items:
                    model_class.objects.bulk_update(
                        updated_items, 
                        ['tmdb_production_country_code', 'tmdb_production_country_eng', 'tmdb_production_country_kr']
                    )
                    total_updated += len(updated_items)
                    self.stdout.write(self.style.SUCCESS(f"✅ 진행률: {total_updated:,} / {total_target:,} 완료"))