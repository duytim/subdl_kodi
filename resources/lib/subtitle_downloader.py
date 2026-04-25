import os
import shutil
import sys
import uuid
import urllib.parse
import traceback

import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.data_collector import get_language_data, get_media_data, get_file_path, convert_language, get_flag
from resources.lib.exceptions import ConfigurationError, ProviderError
from resources.lib.file_operations import get_file_data
from resources.lib.os.provider import SubtitlesProvider
from resources.lib.utilities import get_params, log, error

__addon__ = xbmcaddon.Addon()
__scriptid__ = __addon__.getAddonInfo("id")
__profile__ = xbmcvfs.translatePath(__addon__.getAddonInfo("profile"))
__temp__ = xbmcvfs.translatePath(os.path.join(__profile__, "temp", ""))

# Dọn dẹp thư mục tạm
try:
    if xbmcvfs.exists(__temp__):
        shutil.rmtree(__temp__, ignore_errors=True)
    xbmcvfs.mkdirs(__temp__)
except:
    pass

class SubtitleDownloader:
    def __init__(self):
        # 1. Logic xử lý API Key: Cộng đồng vs Cá nhân
        use_custom = __addon__.getSetting("use_custom_api") == "true"
        if use_custom:
            self.api_key = __addon__.getSetting("APIKey")
            self.tmdb_api_key = __addon__.getSetting("TMDBApiKey")
        else:
            # Key mặc định từ repo gốc của Duy
            self.api_key = "ihGUjWUZckyjq_MA7eOC0Kk6IMfhbB9O"
            self.tmdb_api_key = "c3475734910bdff3c5438b9e6db991ca"

        self.sub_format = "srt"
        self.handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
        self.params = get_params()
        self.subtitles = {}

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
        file_data = get_file_data(get_file_path())
        language_data = get_language_data(self.params)

        if query:
            media_data = {"query": query}
        else:
            media_data = get_media_data()
            if "basename" in file_data:
                media_data["query"] = file_data["basename"]

        try:
            # 2. Logic xử lý Ngôn ngữ: Auto vs Force
            lang_codes = ["AUTO", "VI", "EN", "FR", "DE", "JA", "KO", "ZH"]
            lang_setting_idx = int(__addon__.getSetting("custom_language") or 0)
            
            if lang_setting_idx == 0:
                # Dùng ngôn ngữ tự động từ hệ thống Kodi
                search_langs = language_data.get("languages", "vi").upper()
            else:
                # Dùng ngôn ngữ được chọn cứng trong Settings
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
                
                # Encode URL an toàn để tránh lỗi truyền nhận tham số
                query_params = {"action": "download", "id": subtitle["url"]}
                url = f"plugin://{__scriptid__}/?{urllib.parse.urlencode(query_params)}"
                
                list_item = xbmcgui.ListItem(label=language, label2=file_name)
                list_item.setArt({"thumb": get_flag(subtitle["language"])})
                xbmcplugin.addDirectoryItem(handle=self.handle, url=url, listitem=list_item, isFolder=False)
        xbmcplugin.endOfDirectory(self.handle)