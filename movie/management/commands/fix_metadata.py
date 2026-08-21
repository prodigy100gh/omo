import os
import time
import math
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.core.management.base import BaseCommand
from dotenv import load_dotenv

# 💡 본인의 앱 이름으로 import 경로를 수정하세요!
from movie.models import Movie, TvSeries 

class Command(BaseCommand):
        help = "기존 DB의 '반쪽짜리 제작 국가'와 '누락된 언어' 정보를 1번의 API 호출로 초고속 동시 업데이트합니다."

        def add_arguments(self, parser):
                parser.add_argument('--target', type=str, default='all', choices=['all', 'movie', 'tv'], help='수집 대상 (all, movie, tv)')

        # 💡 글로벌 언어 확장팩
        LANGUAGE_MAP = {
                'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어(표준어)', 'cn': '중국어(광둥어)', 'yue': '광둥어', 
                'tw': '중국어(대만)', 'th': '태국어', 'id': '인도네시아어', 'vi': '베트남어', 'tl': '타갈로그어', 'ms': '말레이어',
                'fr': '프랑스어', 'es': '스페인어', 'de': '독일어', 'it': '이탈리아어', 'pt': '포르투갈어', 'ru': '러시아어', 
                'nl': '네덜란드어', 'pl': '폴란드어', 'uk': '우크라이나어', 'cs': '체코어', 'hu': '헝가리어', 'el': '그리스어', 
                'ro': '루마니아어', 'sv': '스웨덴어', 'da': '덴마크어', 'no': '노르웨이어', 'fi': '핀란드어',
                'ar': '아랍어', 'tr': '튀르키예어', 'he': '히브리어', 'fa': '페르시아어',
                'hi': '힌디어', 'ta': '타밀어', 'te': '텔루구어', 'ml': '말라얄람어',
        }

        def fetch_metadata(self, session, item, media_type, api_key):
                url = f"https://api.themoviedb.org/3/{media_type}/{item.tmdb_id}?api_key={api_key}&language=ko-KR"
                try:
                        response = session.get(url, timeout=5)
                        if response.status_code == 200:
                                data = response.json()
                                
                                # 1. 언어 정보 추출 및 변환
                                lang_code = data.get('original_language', '')
                                lang_val = self.LANGUAGE_MAP.get(lang_code, lang_code.upper()) if lang_code else "확인불가"

                                # 2. 국가 정보 추출 (콤마 분리 로직)
                                countries = data.get('production_countries', [])
                                if media_type == "tv" and not countries:
                                        # TV의 경우 origin_country 배열 활용
                                        codes = data.get('origin_country', [])
                                        engs = codes 
                                else:
                                        codes = [c.get('iso_3166_1', '') for c in countries]
                                        engs = [c.get('name', '') for c in countries]

                                if codes:
                                        krs = [self.get_country_kr_from_code(code) for code in codes]
                                        code_val = ','.join(codes)
                                        eng_val = ', '.join(engs)
                                        kr_val = ', '.join(filter(None, krs))
                                else:
                                        code_val, eng_val, kr_val = "", "", ""

                                return (item, lang_val, code_val, eng_val, kr_val, None)
                        
                        elif response.status_code == 429:
                                time.sleep(1) # API 호출 제한 감지 시 휴식
                                return (item, None, None, None, None, "429 Too Many Requests")
                        else:
                                return (item, None, None, None, None, f"HTTP Error {response.status_code}")
                                
                except Exception as e:
                        return (item, None, None, None, None, f"통신 에러: {str(e)}")

        def process_model(self, model_class, media_type, api_key, session):
                batch_size = 1000
                total_target = model_class.objects.count()

                if total_target == 0:
                        return []

                self.stdout.write(self.style.WARNING(f"\n🚀 [{model_class.__name__}] {total_target:,}개 국가/언어 정보 초고속 수리 시작..."))

                last_id = 0 # Offset(건너뛰기) 대신 마지막 ID 기반의 100% 최적화 커서 탐색
                total_updated = 0
                failed_list = []
                start_time = time.time() # 예상 시간 계산용 기준점

                total_batches = math.ceil(total_target / batch_size)
                current_batch = 0

                while True:
                        items = list(model_class.objects.filter(id__gt=last_id).order_by('id')[:batch_size])
                        if not items:
                                break # 더 이상 데이터가 없으면 탈출

                        last_id = items[-1].id
                        current_batch += 1
                        updated_items = []

                        with ThreadPoolExecutor(max_workers=40) as executor:
                                futures = {executor.submit(self.fetch_metadata, session, item, media_type, api_key): item for item in items}
                                for future in as_completed(futures):
                                        item, lang_val, code_val, eng_val, kr_val, error = future.result()
                                        
                                        if error:
                                                # 에러 발생 시 불량품 목록에 추가
                                                failed_list.append({'id': item.tmdb_id, 'reason': error})
                                        else:
                                                item.tmdb_original_language = lang_val
                                                if code_val: 
                                                        item.tmdb_production_country_code = code_val
                                                        item.tmdb_production_country_eng = eng_val
                                                        item.tmdb_production_country_kr = kr_val
                                                updated_items.append(item)

                        if updated_items:
                                model_class.objects.bulk_update(
                                        updated_items, 
                                        ['tmdb_original_language', 'tmdb_production_country_code', 'tmdb_production_country_eng', 'tmdb_production_country_kr']
                                )
                                total_updated += len(updated_items)

                        # 경과 시간 및 남은 예상 시간(ETA) 동적 계산 로직
                        elapsed = time.time() - start_time
                        avg_time_per_batch = elapsed / current_batch
                        remaining_batches = total_batches - current_batch
                        eta_seconds = avg_time_per_batch * remaining_batches
                        
                        self.stdout.write(self.style.HTTP_INFO(
                                f"  ↳ {current_batch}/{total_batches} 묶음 완료 | ⏳ 소요: {self.format_time(elapsed)} | ⏰ 예상 남은시간: {self.format_time(eta_seconds)} | (총 누적 갱신: {total_updated:,})"
                        ))

                return failed_list

        def handle(self, *args, **options):
                load_dotenv()
                API_KEY = os.getenv("TMDB_API_KEY")
                target = options['target']

                if not API_KEY:
                        self.stdout.write(self.style.ERROR("❌ TMDB_API_KEY가 설정되지 않았습니다."))
                        return

                overall_start_time = time.time() # 전체 작업 시작 시간 측정

                # 429, 500번대 에러 발생 시 최대 5번까지 알아서 재시도하는 무적 세션 이식
                session = requests.Session()
                retries = Retry(total=5, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
                session.mount('https://', HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries))

                global_failed_movies = []
                global_failed_tv = []

                if target in ['all', 'movie']:
                        global_failed_movies = self.process_model(Movie, "movie", API_KEY, session)
                if target in ['all', 'tv']:
                        global_failed_tv = self.process_model(TvSeries, "tv", API_KEY, session)

                overall_elapsed_time = time.time() - overall_start_time

                # 대망의 최종 에러 보고서 출력
                self.stdout.write(self.style.SUCCESS(f"\n🎉 모든 업데이트가 완벽하게 종료되었습니다! (총 소요 시간: {self.format_time(overall_elapsed_time)})"))
                
                if global_failed_movies or global_failed_tv:
                        self.stdout.write(self.style.ERROR("\n======================================================="))
                        self.stdout.write(self.style.ERROR("🚨 [최종 보고서] 끝내 수리/업데이트에 실패한 불량 데이터 목록"))
                        self.stdout.write(self.style.ERROR("======================================================="))
                        
                        if global_failed_movies:
                                self.stdout.write(self.style.WARNING("\n🎬 [영화 실패 목록]"))
                                for fail in global_failed_movies:
                                        self.stdout.write(f" - TMDB ID: {fail['id']} | 사유: {fail['reason']}")
                                        
                        if global_failed_tv:
                                self.stdout.write(self.style.WARNING("\n📺 [TV 시리즈 실패 목록]"))
                                for fail in global_failed_tv:
                                        self.stdout.write(f" - TMDB ID: {fail['id']} | 사유: {fail['reason']}")
                else:
                        self.stdout.write(self.style.SUCCESS("\n🌟 단 하나의 에러도 없이 100% 완벽하게 업데이트되었습니다! 🌟"))

        # =====================================================================
        # 🛠️ [헬퍼 메서드 모음]
        # =====================================================================
        def get_country_kr_from_code(self, code):
                if not code: return "정보 없음"
                code_map = {
                        # 🇰🇷 주요 아시아
                        "KR": "한국", "US": "미국", "JP": "일본", "CN": "중국", "HK": "홍콩", "MO": "마카오", 
                        "TW": "대만", "TH": "태국", "VN": "베트남", "IN": "인도", "ID": "인도네시아", 
                        "PH": "필리핀", "SG": "싱가포르", "MY": "말레이시아", "MN": "몽골", "PK": "파키스탄", 
                        "BD": "방글라데시", "KZ": "카자흐스탄", "NP": "네팔", "KH": "캄보디아", "MM": "미얀마",
                        "UZ": "우즈베키스탄", "KG": "키르기스스탄", "BN": "브루나이", "LA": "라오스",
                        "AF": "아프가니스탄", "TM": "투르크메니스탄", "TJ": "타지키스탄", "BT": "부탄",
                        "KP": "북한", "MV": "몰디브", "TL": "동티모르",
                        
                        # 🌍 유럽 / 러시아 / 코카서스
                        "GB": "영국", "FR": "프랑스", "DE": "독일", "IT": "이탈리아", "ES": "스페인",
                        "NL": "네덜란드", "BE": "벨기에", "SE": "스웨덴", "NO": "노르웨이", "DK": "덴마크", 
                        "FI": "핀란드", "CH": "스위스", "AT": "오스트리아", "PL": "폴란드", "HU": "헝가리", 
                        "CZ": "체코", "SK": "슬로바키아", "GR": "그리스", "PT": "포르투갈", "IE": "아일랜드", 
                        "RO": "루마니아", "UA": "우크라이나", "TR": "터키", "IS": "아이슬란드", "LU": "룩셈부르크",
                        "BG": "불가리아", "RS": "세르비아", "HR": "크로아티아", "LV": "라트비아", "LT": "리투아니아",
                        "EE": "에스토니아", "SI": "슬로베니아", "ME": "몬테네그로", "GE": "조지아", "CY": "키프로스", 
                        "AL": "알바니아", "BA": "보스니아 헤르체고비나", "BY": "벨라루스", "MD": "몰도바",
                        "RU": "러시아", "AM": "아르메니아", "MT": "몰타", "MC": "모나코", "LI": "리히텐슈타인", 
                        "SM": "산마리노", "VA": "바티칸", "AZ": "아제르바이잔", "AD": "안도라", "FO": "페로 제도",
                        "GI": "지브롤터", "IM": "맨섬", "SJ": "스발바르 얀마옌",
                        
                        # 🌮 중남미 & 카리브해
                        "CA": "캐나다", "MX": "멕시코", "BR": "브라질", "AR": "아르헨티나", "CL": "칠레", 
                        "CO": "콜롬비아", "PE": "페루", "CU": "쿠바", "VE": "베네수엘라", "DO": "도미니카 공화국",
                        "GT": "과테말라", "BM": "버뮤다", "AW": "아루바", "JM": "자메이카", "CR": "코스타리카",
                        "UY": "우루과이", "BO": "볼리비아", "PR": "푸에르토리코", "GL": "그린란드", "EC": "에콰도르",
                        "HN": "온두라스", "SV": "엘살바도르", "NI": "니카라과", "PA": "파나마", "PY": "파라과이", 
                        "HT": "아이티", "TT": "트리니다드 토바고", "BS": "바하마", "BZ": "벨리즈", "BB": "바베이도스",
                        "GY": "가이아나", "SR": "수리남", "AG": "앤티가 바부다", "LC": "세인트루시아", 
                        "KN": "세인트키츠 네비스", "VC": "세인트빈센트 그레나딘", "DM": "도미니카 연방", 
                        "GD": "그레나다", "CW": "퀴라소", "GF": "프랑스령 기아나", "GP": "과들루프", "MQ": "마르티니크",
                        "VI": "미국령 버진아일랜드", "VG": "영국령 버진아일랜드", "KY": "케이맨 제도", "MS": "몬트세랫",
                        "TC": "터크스 케이커스 제도", "SX": "신트마르턴", "BQ": "카리브 네덜란드", "BL": "생바르텔레미",
                        "MF": "생마르탱", "PM": "생피에르 미클롱", "FK": "포클랜드 제도",
                        
                        # 🐪 중동 / 아프리카
                        "AU": "호주", "NZ": "뉴질랜드", "ZA": "남아프리카공화국", "IL": "이스라엘", "EG": "이집트", 
                        "SA": "사우디아라비아", "AE": "아랍에미리트", "IR": "이란", "IQ": "이라크", "NG": "나이지리아", 
                        "MA": "모로코", "KE": "케냐", "DZ": "알제리", "TN": "튀니지", "SD": "수단", "MK": "북마케도니아",
                        "LK": "스리랑카", "BF": "부르키나파소", "AQ": "남극", "RW": "르완다", "SY": "시리아", 
                        "LB": "레바논", "LS": "레소토", "SN": "세네갈", "CD": "콩고민주공화국", "CG": "콩고공화국",
                        "CI": "코트디부아르", "KW": "쿠웨이트", "ZW": "짐바브웨", "GH": "가나", "CV": "카보베르데",
                        "QA": "카타르", "OM": "오만", "BH": "바레인", "JO": "요르단", "YE": "예멘", "PS": "팔레스타인",
                        "UG": "우간다", "TZ": "탄자니아", "ET": "에티오피아", "CM": "카메룬", "AO": "앙골라",
                        "MG": "마다가스카르", "ML": "말리", "MU": "모리셔스", "FJ": "피지", "PG": "파푸아뉴기니",
                        "GA": "가봉", "TD": "차드", "TG": "토고", "CF": "중앙아프리카공화국", "GN": "기니", 
                        "GW": "기니비사우", "GQ": "적도 기니", "BI": "부룬디", "BJ": "베냉", "BW": "보츠와나", 
                        "DJ": "지부티", "ER": "에리트레아", "GM": "감비아", "LR": "라이베리아", "MW": "말라위", 
                        "MR": "모리타니", "MZ": "모잠비크", "NA": "나미비아", "NE": "니제르", "SO": "소말리아", 
                        "SZ": "에스와티니", "SC": "세이셸", "ST": "상투메 프린시페", "KM": "코모로", "RE": "레위니옹",
                        "SL": "시에라리온", "SS": "남수단", "EH": "서사하라", "SH": "세인트헬레나", "YT": "마요트",
                        "ZM": "잠비아", "LY": "리비아",
                        
                        # 🏝️ 오세아니아 및 기타 소국
                        "NC": "뉴칼레도니아", "VU": "바누아투", "WS": "사모아", "TO": "통가", "TV": "투발루", 
                        "SB": "솔로몬 제도", "MH": "마셜 제도", "FM": "미크로네시아", "PW": "팔라우", 
                        "NR": "나우루", "KI": "키리바시", "PF": "프랑스령 폴리네시아", "GU": "괌",
                        "AS": "아메리칸 사모아", "CK": "쿡 제도", "NU": "니우에", "PN": "핏케언 제도", 
                        "TK": "토켈라우", "WF": "왈리스 푸투나", "MP": "북마리아나 제도", "UM": "미국령 군소 제도",
                        "CX": "크리스마스섬", "CC": "코코스 제도", "NF": "노퍽섬", "TF": "프랑스령 남부와 남극 지역",
                        "GS": "사우스조지아 사우스샌드위치 제도", "BV": "부베섬", "HM": "허드 맥도널드 제도",
                        "IO": "영국령 인도양 지역", "AX": "올란드 제도",
                        
                        # 🏛️ 역사적 국가 (고전 영화 수집용 TMDB 특수 코드)
                        "SU": "소련", 
                        "YU": "유고슬라비아", 
                        "XC": "체코슬로바키아", 
                        "XG": "동독", 
                        "VD": "남베트남",
                        "CS": "세르비아 몬테네그로", 
                        "AN": "네덜란드령 안틸레스", 
                        
                        # 🌐 특별 분류
                        "XI": "북아일랜드", 
                        "XK": "코소보"
                }
                return code_map.get(code.upper(), f"기타({code.upper()})")

        def format_time(self, seconds):
                hours, remainder = divmod(int(seconds), 3600)
                minutes, secs = divmod(remainder, 60)
                return f"{hours}시간 {minutes}분 {secs}초" if hours > 0 else f"{minutes}분 {secs}초"