import os
import shutil
import sys
import uuid
import urllib.parse
import traceback
import re
from difflib import SequenceMatcher

import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.data_collector import get_language_data, get_media_data, get_file_path, convert_language, get_flag
from resources.lib.exceptions import ConfigurationError, ProviderError
from resources.lib.os.provider import SubtitlesProvider
from resources.lib.utilities import get_params, log, error

__addon__ = xbmcaddon.Addon()
__scriptid__ = __addon__.getAddonInfo("id")
__profile__ = xbmcvfs.translatePath(__addon__.getAddonInfo("profile"))
__temp__ = xbmcvfs.translatePath(os.path.join(__profile__, "temp", ""))

try:
    if xbmcvfs.exists(__temp__):
        shutil.rmtree(__temp__, ignore_errors=True)
    xbmcvfs.mkdirs(__temp__)
except:
    pass

class SubtitleDownloader:
    def __init__(self):
        use_custom = __addon__.getSetting("use_custom_api") == "true"
        if use_custom:
            self.api_key = __addon__.getSetting("APIKey")
            self.tmdb_api_key = __addon__.getSetting("TMDBApiKey")
        else:
            self.api_key = "ihGUjWUZckyjq_MA7eOC0Kk6IMfhbB9O"
            self.tmdb_api_key = "c3475734910bdff3c5438b9e6db991ca"

        # Tùy chọn xử lý hậu kỳ (Post-processing)
        self.remove_html = __addon__.getSetting("remove_html") == "true"
        self.remove_hi = __addon__.getSetting("remove_hi") == "true"

        self.sub_format = "srt"
        self.handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
        self.params = get_params()
        self.subtitles = {}
        self.video_filename = ""

        try:
            self.open_subtitles = SubtitlesProvider(self.api_key, self.tmdb_api_key)
        except ConfigurationError as e:
            error(__name__, 32002, str(e))

    def handle_action(self):
        action = self.params.get("action")
        if action == "manualsearch":
            self.search(self.params.get('searchstring', ''))
        elif action == "search":
            self.search()
        elif action == "download":
            self.download()

    def search(self, query=""):
        self.video_filename = os.path.basename(get_file_path())
        language_data = get_language_data(self.params)

        if query:
            media_data = {"query": query}
        else:
            media_data = get_media_data()
            if not media_data["query"]:
                media_data["query"] = self.video_filename

        try:
            lang_codes = ["AUTO", "VI", "EN", "FR", "DE", "JA", "KO", "ZH"]
            lang_setting_idx = int(__addon__.getSetting("custom_language") or 0)
            
            if lang_setting_idx == 0:
                search_langs = language_data.get("languages", "vi").upper()
            else:
                search_langs = lang_codes[lang_setting_idx]
                
            log(__name__, f"Search initiated with language: {search_langs}")
            self.subtitles = self.open_subtitles.search_subtitles(media_data, search_langs)
            
        except Exception as e:
            error(__name__, 32001, str(e))

        if self.subtitles:
            self.list_subtitles()
        else:
            log(__name__, "No subtitle found")

    def download(self):
        valid = 1
        try:
            file_id = self.params["id"]
            self.file_content = self.open_subtitles.download_subtitle({"file_id": file_id})
            
            # Post-Processing: Dọn rác phụ đề
            if self.file_content and (self.remove_html or self.remove_hi):
                try:
                    text = self.file_content.decode('utf-8', errors='ignore')
                    if self.remove_html:
                        text = re.sub(r'<[^>]+>', '', text) # Xóa mã màu, font
                    if self.remove_hi:
                        text = re.sub(r'\[.*?\]|\(.*?\)', '', text) # Xóa tag âm thanh
                    self.file_content = text.encode('utf-8')
                except Exception as e:
                    log(__name__, f"Post-processing failed: {e}")

        except Exception as e:
            log(__name__, f"Download Error: {traceback.format_exc()}")
            error(__name__, 32001, f"Download failed: {str(e)}")
            valid = 0

        if valid == 1 and self.file_content:
            subtitle_path = os.path.join(__temp__, f"{str(uuid.uuid4())}.{self.sub_format}")
            try:
                with open(subtitle_path, "wb") as f:
                    f.write(self.file_content)
                
                list_item = xbmcgui.ListItem(label=subtitle_path)
                xbmcplugin.addDirectoryItem(handle=self.handle, url=subtitle_path, listitem=list_item, isFolder=False)
            except Exception as e:
                log(__name__, f"File Write Error: {str(e)}")

    def list_subtitles(self):
        if self.subtitles:
            for subtitle in self.subtitles:
                language = convert_language(subtitle["language"], True)
                file_name = subtitle["release_name"]
                
                # Thuật toán so sánh tên: Đánh dấu [★ SYNC] cho phụ đề khớp khung hình (Web-DL, Bluray, v.v...)
                ratio = SequenceMatcher(None, self.video_filename.lower(), file_name.lower()).ratio()
                if ratio > 0.85 or file_name.lower() in self.video_filename.lower():
                    file_name = f"[COLOR lime]★ [SYNC][/COLOR] {file_name}"
                
                query_params = {"action": "download", "id": subtitle["url"]}
                url = f"plugin://{__scriptid__}/?{urllib.parse.urlencode(query_params)}"
                
                list_item = xbmcgui.ListItem(label=language, label2=file_name)
                list_item.setArt({"thumb": get_flag(subtitle["language"])})
                xbmcplugin.addDirectoryItem(handle=self.handle, url=url, listitem=list_item, isFolder=False)
        xbmcplugin.endOfDirectory(self.handle)