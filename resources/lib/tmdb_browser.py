"""
TMDB Search & Movie Selection Dialog

Handles:
1. Search TMDB by title/year
2. Display selection UI if multiple results
3. Auto-select if threshold met
4. Get IMDB ID from TMDB
"""

import re
from typing import Dict, Optional, List, Tuple
from difflib import SequenceMatcher
from urllib.parse import urlencode

import xbmc
import xbmcgui
import xbmcaddon

from resources.lib.utilities import log
from resources.lib.cache import Cache
from resources.lib.exceptions import ProviderError

__addon__ = xbmcaddon.Addon()


class TMDbBrowser:
    """Handle TMDB search & selection flow"""

    def __init__(self, provider):
        """
        Args:
            provider: SubtitlesProvider instance (for API calls)
        """
        self.provider = provider
        self.cache = Cache(key_prefix="tmdb_browser")
        self.auto_select_threshold = int(
            __addon__.getSetting("auto_select_threshold") or 85
        )

    def search_and_select(
        self,
        query: str,
        year: Optional[str] = None,
        media_type: str = "movie",
        original_filename: str = "",
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Search TMDB và tùy chọn chọn phim

        Args:
            query: Tên phim/show
            year: Năm phát hành
            media_type: "movie" hoặc "tv"
            original_filename: Tên file gốc (dùng để auto-select)

        Returns:
            (tmdb_id, imdb_id) hoặc (None, None) nếu user cancel

        Raises:
            ProviderError: Nếu TMDB API error
        """

        log(__name__, f"Searching {media_type}: {query} ({year})")

        # 1. Search TMDB
        results = self._search_tmdb(query, year, media_type)

        if not results:
            raise ProviderError(f"TMDB: No {media_type} found for '{query}'")

        log(__name__, f"Found {len(results)} result(s)")

        # 2. Auto-select logic
        selected = self._auto_select(results, query, year, original_filename)

        if selected:
            log(__name__, f"Auto-selected: {selected['title']}")
            tmdb_id = selected["id"]
        else:
            # 3. User selection UI (chỉ nếu không auto-select)
            selected = self._show_selection_dialog(results, media_type)

            if not selected:
                log(__name__, "User cancelled movie selection")
                return None, None

            tmdb_id = selected["id"]

        # 4. Get IMDB ID
        imdb_id = self._get_imdb_id(tmdb_id, media_type)

        return str(tmdb_id), imdb_id

    def _search_tmdb(
        self, query: str, year: Optional[str], media_type: str
    ) -> List[Dict]:
        """
        Search TMDB API

        Returns:
            List of movie/tv dicts với keys: id, title, year, overview, poster_path, popularity
        """

        # Check cache
        cache_key = f"search_{media_type}_{query}_{year or ''}"
        cached = self.cache.get(cache_key)
        if cached:
            log(__name__, f"TMDB cache hit: {cache_key}")
            return cached

        # Build URL
        url = f"https://api.themoviedb.org/3/search/{media_type}"
        params = {
            "api_key": self.provider.tmdb_api_key,
            "query": query,
            "include_adult": "false",
        }

        if year:
            if media_type == "tv":
                params["first_air_date_year"] = year
            else:
                params["year"] = year

        # API call
        try:
            full_url = url + "?" + urlencode(params)
            data = self.provider.handle_request(full_url)
        except Exception as e:
            raise ProviderError(f"TMDB search failed: {str(e)}")

        if "results" not in data:
            raise ProviderError("TMDB: Invalid response format")

        # Parse results
        results = []
        for item in data["results"][:10]:  # Top 10 results
            result = {
                "id": item.get("id"),
                "title": item.get("title" if media_type == "movie" else "name", "Unknown"),
                "year": self._extract_year(item, media_type),
                "overview": item.get("overview", "")[:200],  # Truncate
                "poster_path": item.get("poster_path"),
                "popularity": item.get("popularity", 0),
                "original_title": item.get(
                    "original_title" if media_type == "movie" else "original_name", ""
                ),
            }

            if result["id"]:
                results.append(result)

        # Cache 7 days
        if results:
            self.cache.set(cache_key, results, expires=60 * 60 * 24 * 7)

        return results

    def _auto_select(
        self,
        results: List[Dict],
        query: str,
        year: Optional[str],
        filename: str,
    ) -> Optional[Dict]:
        """
        Auto-select phim nếu đạt threshold

        Criteria:
        1. Exact match hoặc title similarity > threshold
        2. Year match (nếu có)
        3. Popularity cao nhất

        Returns:
            Selected dict hoặc None
        """

        candidates = []

        for result in results:
            score = 0
            reasons = []

            # Title similarity
            title_match = SequenceMatcher(
                None, query.lower(), result["title"].lower()
            ).ratio()

            title_original_match = SequenceMatcher(
                None, query.lower(), result.get("original_title", "").lower()
            ).ratio()

            title_score = max(title_match, title_original_match)
            score += int(title_score * 100)

            if title_score > 0.95:
                reasons.append(f"Title match {title_score*100:.0f}%")

            # Year match
            if year and str(result.get("year")) == str(year):
                score += 10
                reasons.append("Year match")
            elif year:
                year_diff = abs(int(result.get("year") or 0) - int(year))
                if year_diff <= 1:
                    score += 5
                    reasons.append(f"Year ±{year_diff}")

            # Popularity bonus
            popularity_bonus = min(int(result["popularity"] / 10), 10)
            score += popularity_bonus

            # Filename match (fallback)
            if filename:
                file_match = SequenceMatcher(
                    None, filename.lower(), result["title"].lower()
                ).ratio()
                if file_match > 0.85:
                    score += 5
                    reasons.append(f"Filename match {file_match*100:.0f}%")

            candidates.append(
                {"result": result, "score": score, "reasons": reasons}
            )

            log(
                __name__,
                f"Score {result['title']}: {score} ({', '.join(reasons)})",
            )

        # Sort by score
        candidates.sort(key=lambda x: x["score"], reverse=True)

        if not candidates:
            return None

        top_score = candidates[0]["score"]

        # Auto-select nếu score >= threshold
        if top_score >= self.auto_select_threshold:
            log(
                __name__,
                f"Auto-select: {candidates[0]['result']['title']} (score {top_score})",
            )
            return candidates[0]["result"]

        # Nếu có separator lớn giữa top 2
        if len(candidates) > 1:
            gap = top_score - candidates[1]["score"]
            if gap >= 20:  # 20+ điểm khác biệt
                log(
                    __name__,
                    f"Clear winner: {candidates[0]['result']['title']} (gap {gap})",
                )
                return candidates[0]["result"]

        log(__name__, f"Multiple candidates, showing UI (top score: {top_score})")
        return None

    def _show_selection_dialog(
        self, results: List[Dict], media_type: str
    ) -> Optional[Dict]:
        """
        Hiển thị dialog chọn phim trong Kodi

        Returns:
            Selected result dict hoặc None (user cancel)
        """

        dialog = xbmcgui.Dialog()

        # Build items list
        items = []
        for result in results:
            label = f"{result['title']}"

            if result.get("year"):
                label += f" ({result['year']})"

            item = xbmcgui.ListItem(label=label)

            # Set poster
            if result.get("poster_path"):
                poster_url = f"https://image.tmdb.org/t/p/w342{result['poster_path']}"
                item.setArt({"poster": poster_url})

            # Set info
            info = {
                "title": result["title"],
                "plot": result.get("overview", ""),
                "year": result.get("year"),
                "mediatype": media_type,
            }

            if result.get("popularity"):
                info["rating"] = min(result["popularity"] / 10, 10)

            item.setInfo("video", info)

            items.append(item)
            result["_listitem"] = item

        # Show selection dialog
        title = f"Select {media_type.capitalize()}"
        selected_idx = dialog.select(title, items, useDetails=True)

        if selected_idx < 0:
            return None  # User cancelled

        return results[selected_idx]

    def _get_imdb_id(self, tmdb_id: str, media_type: str) -> Optional[str]:
        """
        Get IMDB ID from TMDB

        Returns:
            IMDB ID string (tt...) hoặc None
        """

        # Check cache
        cache_key = f"imdb_id_{tmdb_id}"
        cached = self.cache.get(cache_key)
        if cached:
            log(__name__, f"IMDB ID cache hit: {cached}")
            return cached

        # API call
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids"
        params = {"api_key": self.provider.tmdb_api_key}

        try:
            full_url = url + "?" + urlencode(params)
            data = self.provider.handle_request(full_url)
            imdb_id = data.get("imdb_id")

            if imdb_id:
                # Cache 30 days
                self.cache.set(cache_key, imdb_id, expires=60 * 60 * 24 * 30)
                log(__name__, f"Got IMDB ID: {imdb_id}")
                return imdb_id
        except Exception as e:
            log(__name__, f"Failed to get IMDB ID: {str(e)}")

        return None

    def _extract_year(self, item: Dict, media_type: str) -> Optional[int]:
        """Extract year from TMDB response"""

        date_key = "release_date" if media_type == "movie" else "first_air_date"
        date_str = item.get(date_key, "")

        if date_str:
            try:
                return int(date_str[:4])
            except (ValueError, IndexError):
                pass

        return None
