"""
Search endpoints — search external sources (Spotify, iTunes, Hydrabase).
"""

from flask import request, current_app
from .auth import require_api_key
from .helpers import api_success, api_error


def register_routes(bp):

    @bp.route("/search/tracks", methods=["POST"])
    @require_api_key
    def search_tracks():
        """Search for tracks across music sources.

        Body: {"query": "...", "source": "spotify"|"itunes"|"deezer"|"discogs"|"hydrabase"|"auto", "limit": 20}
        """
        body = request.get_json(silent=True) or {}
        query = body.get("query", "").strip()
        source = body.get("source", "auto")
        limit = min(50, max(1, int(body.get("limit", 20))))

        if not query:
            return api_error("BAD_REQUEST", "Missing 'query' in request body.", 400)

        try:
            ctx = current_app.soulsync
            spotify = ctx.get("spotify_client")
            from core.metadata_service import get_metadata_client_for_source

            client, resolved_source = get_metadata_client_for_source(source, spotify_client=spotify)
            if resolved_source == "spotify" and spotify and not spotify.is_spotify_authenticated():
                return api_success({"tracks": [], "source": "spotify"})

            results = client.search_tracks(query, limit=limit)
            tracks = [_serialize_track(t) for t in results] if results else []
            return api_success({"tracks": tracks, "source": resolved_source})
        except Exception as e:
            return api_error("SEARCH_ERROR", str(e), 500)

    @bp.route("/search/albums", methods=["POST"])
    @require_api_key
    def search_albums():
        """Search for albums.

        Body: {"query": "...", "limit": 20}
        """
        body = request.get_json(silent=True) or {}
        query = body.get("query", "").strip()
        limit = min(50, max(1, int(body.get("limit", 20))))

        if not query:
            return api_error("BAD_REQUEST", "Missing 'query' in request body.", 400)

        try:
            ctx = current_app.soulsync
            spotify = ctx.get("spotify_client")
            from core.metadata_service import get_metadata_client_for_source

            client, resolved_source = get_metadata_client_for_source("auto", spotify_client=spotify)
            results = client.search_albums(query, limit=limit)
            return api_success({
                "albums": [_serialize_album(a) for a in results] if results else [],
                "source": resolved_source,
            })
        except Exception as e:
            return api_error("SEARCH_ERROR", str(e), 500)

    @bp.route("/search/artists", methods=["POST"])
    @require_api_key
    def search_artists():
        """Search for artists.

        Body: {"query": "...", "limit": 20}
        """
        body = request.get_json(silent=True) or {}
        query = body.get("query", "").strip()
        limit = min(50, max(1, int(body.get("limit", 20))))

        if not query:
            return api_error("BAD_REQUEST", "Missing 'query' in request body.", 400)

        try:
            ctx = current_app.soulsync
            spotify = ctx.get("spotify_client")
            from core.metadata_service import get_metadata_client_for_source

            client, resolved_source = get_metadata_client_for_source("auto", spotify_client=spotify)
            results = client.search_artists(query, limit=limit)
            return api_success({
                "artists": [_serialize_artist(a) for a in results] if results else [],
                "source": resolved_source,
            })
        except Exception as e:
            return api_error("SEARCH_ERROR", str(e), 500)


# ---- serialization (from core dataclasses) ----

def _serialize_track(t):
    return {
        "id": t.id,
        "name": t.name,
        "artists": t.artists,
        "album": t.album,
        "duration_ms": t.duration_ms,
        "popularity": t.popularity,
        "preview_url": t.preview_url,
        "image_url": t.image_url,
        "release_date": t.release_date,
    }


def _serialize_album(a):
    return {
        "id": a.id,
        "name": a.name,
        "artists": a.artists,
        "release_date": a.release_date,
        "total_tracks": a.total_tracks,
        "album_type": a.album_type,
        "image_url": a.image_url,
    }


def _serialize_artist(a):
    return {
        "id": a.id,
        "name": a.name,
        "popularity": a.popularity,
        "genres": a.genres,
        "followers": a.followers,
        "image_url": a.image_url,
    }
