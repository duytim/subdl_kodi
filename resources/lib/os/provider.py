import zipfile
import io
import re
from requests import Session, ConnectionError, HTTPError, ReadTimeout, Timeout

from resources.lib.exceptions import ConfigurationError, ProviderError, ServiceUnavailable, TooManyRequests
from resources.lib.cache import Cache
from resources.lib.utilities import log

API_URL = "https://api.subdl.com/api/v1/subtitles"
TMDB_API = "https://api.themoviedb.org/3/search"
CONTENT_TYPE = "application/json"
REQUEST_TIMEOUT = 30

CLEAN_PATTERN_1 = re.compile(r'\.\d+p.*|\.(mkv|avi|mp4)$|\(.*?\)', re.IGNORECASE)
CLEAN_PATTERN_2 = re.compile(r'\.(?=[A-Z])|\.')
YEAR_PATTERN = re.compile(r'\b(19[0-9]{2}|20[0-9]{2})\b')
TV_PATTERN = re.compile(r'S(\d+)E(\d+)', re.IGNORECASE)
TV_CLEAN_PATTERN = re.compile(r'\s*S\d+E\d+.*', re.IGNORECASE)

def logging(msg):
    return log(__name__, msg)

class SubtitlesProvider:
    def __init__(self, api_key, tmdb_api_key):
        if not api_key:
            raise ConfigurationError("SubDL API must be specified")
        if not tmdb_api_key:
            raise ConfigurationError("TMDB API must be specified")

        self.api_key = api_key
        self.tmdb_api_key = tmdb_api_key
        
        self.request_headers = {
            "Content-Type": CONTENT_TYPE, 
            "Accept": CONTENT_TYPE,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        self.session = Session()
        self.session.headers.update(self.request_headers)
        
        # Khởi tạo Cache
        self.cache = Cache(key_prefix="subdl_cache")

    def handle_request(self, url):
        try:
            r = self.session.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except (ConnectionError, Timeout, ReadTimeout) as e:
            raise ServiceUnavailable(f"Network Error: {e!r}")
        except HTTPError as e:
            status_code = e.response.status_code
            if status_code == 429:
                raise TooManyRequests()
            elif status_code == 503:
                raise ProviderError(e)
            else:
                raise ProviderError(f"Bad status code: {status_code}")
        return r.json()

    def parse_filename(self, filename):
        clean_name = CLEAN_PATTERN_1.sub('', filename)
        clean_name = CLEAN_PATTERN_2.sub(' ', clean_name)
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()

        year_match = YEAR_PATTERN.search(clean_name)
        year = year_match.group(0) if year_match else None

        series_match = TV_PATTERN.search(filename)
        if series_match:
            title = TV_CLEAN_PATTERN.sub('', clean_name[:year_match.start() if year_match else None]).strip()
            return {
                "title": title.rstrip('.').strip(),
                "year": year,
                "type": "tv",
                "season_number": series_match.group(1),
                "episode_number": series_match.group(2)
            }
        else:
            title = clean_name[:year_match.start()] if year_match else clean_name
            return {
                "title": title.strip().rstrip('.'),
                "year": year,
                "type": "movie",
                "season_number": None,
                "episode_number": None
            }

    def get_tmdb_id(self, metadata):
        # 1. Kiểm tra trong Cache trước khi gọi API
        cache_key = f"tmdb_{metadata['type']}_{metadata['title']}_{metadata.get('year', '')}"
        cached_id = self.cache.get(cache_key)
        if cached_id:
            logging(f"TMDB ID loaded from cache: {cached_id}")
            return cached_id

        # 2. Nếu không có trong Cache, gọi API
        url = f"{TMDB_API}/{metadata['type']}?query={metadata['title']}&api_key={self.tmdb_api_key}"
        if metadata.get('year'):
            url += f"&year={metadata['year']}"
            
        data = self.handle_request(url)
        if "results" not in data or not data["results"]:
            raise ProviderError("TMDB: Movie/TV Show not found.")
            
        tmdb_id = data["results"][0]["id"]
        # Lưu vào Cache để dùng cho lần sau (mặc định cache 7 ngày)
        self.cache.set(cache_key, tmdb_id)
        return tmdb_id

    def search_subtitles(self, media_data: dict, languages: str):
        metadata = self.parse_filename(media_data['query'])
        imdb_id = media_data.get("imdb_id")
        
        # Tối ưu siêu tốc: Nếu Kodi đã quét được IMDB ID, gọi thẳng cho SubDL, bỏ qua TMDB
        if imdb_id and str(imdb_id).startswith("tt"):
            logging("Using direct IMDB ID from Kodi")
            url = f"{API_URL}?api_key={self.api_key}&type={metadata['type']}&languages={languages}&imdb_id={imdb_id}"
        else:
            tmdbID = self.get_tmdb_id(metadata)
            url = f"{API_URL}?api_key={self.api_key}&type={metadata['type']}&languages={languages}&tmdb_id={tmdbID}"
            
        if metadata['type'] == 'tv':
            url += f"&season_number={metadata['season_number']}&episode_number={metadata['episode_number']}"
            
        result = self.handle_request(url)
        if "subtitles" not in result:
            raise ProviderError("Invalid JSON returned by SubDL")
            
        logging(f"Query returned {len(result['subtitles'])} subtitles")
        return result["subtitles"] if result["subtitles"] else None
    
    def download_subtitle(self, query: dict):
        sub_id = query["file_id"]
        
        if sub_id.startswith("http"):
            download_link = sub_id
        elif sub_id.startswith("/"):
            download_link = "https://dl.subdl.com" + sub_id
        else:
            download_link = "https://dl.subdl.com/" + sub_id
            
        res = self.session.get(download_link, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()

        try:
            with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                valid_extensions = ('.srt', '.ass', '.vtt', '.sub', '.ssa')
                file_name = None
                
                for name in z.namelist():
                    if name.lower().endswith(valid_extensions):
                        file_name = name
                        break
                
                if not file_name:
                    raise ProviderError("No valid subtitle file (.srt, .ass, etc.) found in the ZIP archive.")
                    
                file_content = z.read(file_name)
        except zipfile.BadZipFile as e:
            logging(f"Failed to unzip subtitle: {e}")
            raise ProviderError(f"Failed to unzip subtitle: {e}")

        return file_content