from urllib.parse import unquote
import xbmc
import xbmcaddon
from resources.lib.utilities import log, normalize_string

__addon__ = xbmcaddon.Addon()

def get_file_path():
    return xbmc.Player().getPlayingFile()

def get_media_data():
    item = {
        "query": None,
        "year": xbmc.getInfoLabel("VideoPlayer.Year"),
        "season_number": str(xbmc.getInfoLabel("VideoPlayer.Season")),
        "episode_number": str(xbmc.getInfoLabel("VideoPlayer.Episode")),
        "tv_show_title": normalize_string(xbmc.getInfoLabel("VideoPlayer.TVshowtitle")),
        "original_title": normalize_string(xbmc.getInfoLabel("VideoPlayer.OriginalTitle")),
        "imdb_id": xbmc.getInfoLabel("VideoPlayer.IMDBNumber") # Tận dụng IMDB ID có sẵn của Kodi
    }

    if item["tv_show_title"]:
        item["query"] = item["tv_show_title"]
        item["year"] = None  
    elif item["original_title"]:
        item["query"] = item["original_title"]

    if not item["query"]:
        log(__name__, "query still blank, fallback to title")
        item["query"] = normalize_string(xbmc.getInfoLabel("VideoPlayer.Title"))

    if item["episode_number"].lower().find("s") > -1:  
        item["season_number"] = "0"  
        item["episode_number"] = item["episode_number"][-1:]

    return item

def get_language_data(params):
    search_languages = unquote(params.get("languages", "")).split(",")
    search_languages_str = ""
    preferred_language = params.get("preferredlanguage")

    if preferred_language and preferred_language not in search_languages and preferred_language not in ["Unknown", "Undetermined"]:
        search_languages.append(preferred_language)
        search_languages_str = search_languages_str + "," + preferred_language if search_languages_str else preferred_language

    for language in search_languages:
        lang = convert_language(language)
        if lang:
            if search_languages_str == "":
                search_languages_str = lang
            else:
                search_languages_str = search_languages_str + "," + lang

    return {
        "languages": search_languages_str
    }

def convert_language(language, reverse=False):
    language_list = {
        "English": "en",
        "Portuguese (Brazil)": "pt-br",
        "Portuguese": "pt-pt",
        "Chinese (simplified)": "zh-cn",
        "Chinese (traditional)": "zh-tw"
    }
    reverse_language_list = {v: k for k, v in list(language_list.items())}

    if reverse:
        iterated_list = reverse_language_list
        xbmc_param = xbmc.ENGLISH_NAME
    else:
        iterated_list = language_list
        xbmc_param = xbmc.ISO_639_1

    if language in iterated_list:
        return iterated_list[language]
    else:
        return xbmc.convertLanguage(language, xbmc_param)

def get_flag(language_code):
    language_list = {
        "pt-pt": "pt",
        "pt-br": "pb"
    }
    return language_list.get(language_code.lower(), language_code)