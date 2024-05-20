Add-on only supports Vietnamese subtitles

Change the language in service.subtitles.subdl-com\resources\lib\os\provider.py at line 105.

|url = f"{API_URL}?api_key={self.api_key}&type={metadata['type']}&languages=VI&tmdb_id={tmdbID}"|
Change the subdl API in service.subtitles.subdl-com\resources\settings.xml at line 12 inside <default></default>.
Source: https://github.com/opensubtitlesdev/service.subtitles.opensubtitles-com

SubDL API-Key: https://subdl.com/panel/api
ThemovieDB API-Key: https://www.themoviedb.org/settings/api

![App Screenshot](https://i.postimg.cc/L4QCZxJr/Screenshot-2024-05-13-at-08-57-23.png)

![App Screenshot](https://i.postimg.cc/vH1P759D/Screenshot-2024-05-13-at-08-58-16.png)


