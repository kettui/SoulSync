import types

from core.metadata_service import (
    MetadataService,
    get_configured_non_spotify_metadata_source,
    get_configured_primary_metadata_source,
    get_primary_metadata_client,
    get_primary_metadata_source,
)
from core.personalized_playlists import PersonalizedPlaylistsService
from core.seasonal_discovery import SeasonalDiscoveryService
from core.watchlist_scanner import WatchlistScanner
from ui.components.watchlist_status_modal import WatchlistScanWorker


class DummyConn:
    def __init__(self, rows=None):
        self._rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self

    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return self._rows


class PlaylistDbStub:
    def _get_connection(self):
        return DummyConn()


class PlaylistDbWithMappedSimilarStub:
    def _get_connection(self):
        class Cursor:
            def __init__(self):
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return self

            def execute(self, _query, params):
                self.params = params

            def fetchall(self):
                if self.params == ("222", "222", "222", "222", "222"):
                    return [{"similar_artist_id": "333", "similar_artist_name": "Mapped Similar"}]
                return []

        return Cursor()


class SeasonalDbStub:
    def get_watchlist_artists(self):
        return [
            types.SimpleNamespace(
                artist_name="Winter Artist",
                spotify_artist_id="spotify-artist",
                itunes_artist_id="111",
                deezer_artist_id="222",
            )
        ]


class WatchlistDbStub:
    def should_populate_discovery_pool(self, hours_threshold=6, profile_id=1):
        return True

    def get_watchlist_artists(self, profile_id=1):
        return [
            types.SimpleNamespace(
                artist_name="Provider Artist",
                spotify_artist_id="spotify-artist",
                itunes_artist_id="111",
                deezer_artist_id="222",
            )
        ]

    def clear_discovery_recent_albums(self, profile_id=1):
        return None

    def get_top_similar_artists(self, limit=50, profile_id=1):
        return []

    def cache_discovery_recent_album(self, album_data, source="spotify", profile_id=1):
        return True

    def update_discovery_pool_timestamp(self, track_count, profile_id=1):
        return None

    def add_to_discovery_pool(self, track_data, source="spotify", profile_id=1):
        return True

    def _get_connection(self):
        class Conn:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                return False

            def cursor(self_inner):
                return self_inner

            def execute(self_inner, *args, **kwargs):
                return None

            def fetchone(self_inner):
                return {"count": 1}

        return Conn()

    def cleanup_old_discovery_tracks(self, days_threshold=365):
        return 0


class FallbackAlbumsClient:
    def __init__(self):
        self.artist_album_calls = []
        self.album_calls = []

    def search_artists(self, query, limit=5):
        return [types.SimpleNamespace(id="222", name=query, image_url=None)]

    def get_artist_albums(self, artist_id, album_type="album,single", limit=50, **kwargs):
        self.artist_album_calls.append((artist_id, album_type, limit, kwargs))
        return [
            types.SimpleNamespace(
                id="album-1",
                name="Christmas Collection",
                release_date="2025-12-01",
                album_type="album",
                image_url=None,
            )
        ]

    def get_album(self, album_id, include_tracks=True):
        self.album_calls.append(album_id)
        return {
            "id": album_id,
            "name": "Christmas Collection",
            "release_date": "2025-12-01",
            "album_type": "album",
            "images": [],
            "tracks": {
                "items": [
                    {
                        "id": "track-1",
                        "name": "Holiday Song",
                        "duration_ms": 180000,
                        "artists": [{"name": "Winter Artist"}],
                    }
                ]
            },
        }

    def get_album_tracks(self, album_id):
        return {"items": [{"id": "track-1", "name": "Holiday Song", "duration_ms": 180000}]}

    def get_artist(self, artist_id):
        return {"genres": ["holiday"]}


class SpotifyStub:
    def __init__(self):
        self.sp = object()
        self.artist_album_calls = []
        self.artist_calls = []
        self.album_calls = []

    def is_spotify_authenticated(self):
        return True

    def is_authenticated(self):
        return True

    def get_artist_albums(self, *args, **kwargs):
        self.artist_album_calls.append((args, kwargs))
        return []

    def get_artist(self, artist_id):
        self.artist_calls.append(artist_id)
        return {"name": "Spotify Artist"}

    def get_album(self, album_id):
        self.album_calls.append(album_id)
        return None

    def get_album_tracks(self, album_id):
        return {"items": []}


def test_get_primary_metadata_source_prefers_configured_provider_when_spotify_authenticated(monkeypatch):
    spotify_client = SpotifyStub()
    monkeypatch.setattr("core.metadata_service.get_configured_primary_metadata_source", lambda default="deezer": "deezer")

    assert get_primary_metadata_source(spotify_client) == "deezer"


def test_configured_primary_source_defaults_to_deezer_when_unset(monkeypatch):
    monkeypatch.setattr("config.settings.config_manager.get", lambda _key, default=None: None)

    assert get_configured_primary_metadata_source() == "deezer"


def test_non_spotify_metadata_source_defaults_to_deezer_when_primary_is_spotify(monkeypatch):
    monkeypatch.setattr("config.settings.config_manager.get", lambda _key, default=None: "spotify")

    assert get_configured_non_spotify_metadata_source() == "deezer"


def test_get_primary_metadata_client_reuses_shared_spotify_client(monkeypatch):
    created_clients = []

    class SharedSpotifyStub(SpotifyStub):
        def __init__(self):
            super().__init__()
            created_clients.append(self)

    monkeypatch.setattr("core.metadata_service._shared_spotify_client", None)
    monkeypatch.setattr("core.metadata_service.get_configured_primary_metadata_source", lambda default="deezer": "spotify")
    monkeypatch.setattr("core.metadata_service.SpotifyClient", SharedSpotifyStub)

    first_client, first_provider = get_primary_metadata_client()
    second_client, second_provider = get_primary_metadata_client()

    assert first_provider == "spotify"
    assert second_provider == "spotify"
    assert first_client is second_client
    assert len(created_clients) == 1


def test_metadata_service_auto_uses_configured_primary_provider(monkeypatch):
    spotify_client = SpotifyStub()
    service = MetadataService.__new__(MetadataService)
    service.preferred_provider = "auto"
    service.spotify = spotify_client
    service._primary_source = "deezer"
    service.non_spotify = FallbackAlbumsClient()
    service.itunes = FallbackAlbumsClient()

    monkeypatch.setattr("core.metadata_service.get_primary_metadata_source", lambda *_args, **_kwargs: "deezer")

    assert service.get_active_provider() == "deezer"


def test_metadata_service_primary_is_compatibility_alias_for_auto(monkeypatch):
    spotify_client = SpotifyStub()
    service = MetadataService.__new__(MetadataService)
    service.preferred_provider = "primary"
    service.spotify = spotify_client
    service._primary_source = "deezer"
    service.non_spotify = FallbackAlbumsClient()
    service.itunes = FallbackAlbumsClient()

    monkeypatch.setattr("core.metadata_service.get_primary_metadata_source", lambda *_args, **_kwargs: "deezer")

    assert service.get_active_provider() == "deezer"


def test_metadata_service_itunes_is_explicit_itunes_not_non_spotify(monkeypatch):
    spotify_client = SpotifyStub()
    service = MetadataService.__new__(MetadataService)
    service.preferred_provider = "itunes"
    service.spotify = spotify_client
    service._primary_source = "deezer"
    service.non_spotify = FallbackAlbumsClient()
    service.itunes = service.non_spotify
    service._provider_client_cache = {}

    assert service.get_active_provider() == "itunes"


def test_seasonal_discovery_uses_primary_client_not_spotify(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()

    monkeypatch.setattr(SeasonalDiscoveryService, "_ensure_database_schema", lambda self: None)
    monkeypatch.setattr(
        "core.metadata_service.get_primary_metadata_client",
        lambda *_args, **_kwargs: (fallback_client, "deezer"),
    )
    monkeypatch.setattr("core.metadata_service.get_primary_metadata_source", lambda *_args, **_kwargs: "deezer")

    service = SeasonalDiscoveryService(spotify_client, SeasonalDbStub())
    albums = service._search_watchlist_seasonal_albums("christmas")

    assert albums
    assert fallback_client.artist_album_calls
    assert spotify_client.artist_album_calls == []


def test_build_custom_playlist_uses_primary_client_for_album_fetches(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()

    monkeypatch.setattr(
        "core.metadata_service.get_primary_metadata_client",
        lambda *_args, **_kwargs: (fallback_client, "deezer"),
    )
    monkeypatch.setattr("core.metadata_service.get_primary_metadata_source", lambda *_args, **_kwargs: "deezer")
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    service = PersonalizedPlaylistsService(PlaylistDbStub(), spotify_client)
    result = service.build_custom_playlist(["222"], playlist_size=10)

    assert result["tracks"]
    assert fallback_client.artist_album_calls
    assert spotify_client.artist_album_calls == []


def test_build_custom_playlist_resolves_cached_similar_artists_for_deezer_seed(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()

    monkeypatch.setattr(
        "core.metadata_service.get_primary_metadata_client",
        lambda *_args, **_kwargs: (fallback_client, "deezer"),
    )
    monkeypatch.setattr("core.metadata_service.get_primary_metadata_source", lambda *_args, **_kwargs: "deezer")
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    service = PersonalizedPlaylistsService(PlaylistDbWithMappedSimilarStub(), spotify_client)
    result = service.build_custom_playlist(["222"], playlist_size=10)

    assert result["tracks"]
    assert any(call[0] == "333" for call in fallback_client.artist_album_calls)


def test_watchlist_scan_worker_uses_provider_aware_discography(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()

    class FakeScanner:
        def __init__(self):
            self.provider_aware_called = False

        def get_active_client_and_artist_id(self, watchlist_artist):
            return fallback_client, watchlist_artist.deezer_artist_id, "deezer"

        def get_artist_discography(self, spotify_artist_id, last_scan_timestamp=None):
            raise AssertionError("Legacy Spotify-only watchlist path should not be used")

        def get_artist_discography_for_watchlist(self, watchlist_artist, last_scan_timestamp=None):
            self.provider_aware_called = True
            return [types.SimpleNamespace(id="album-1", name="Fallback Album")]

        def _should_include_release(self, track_count, watchlist_artist):
            return True

        def is_track_missing_from_library(self, track):
            return False

        def add_track_to_wishlist(self, track, album_data, watchlist_artist):
            return False

        def update_artist_scan_timestamp(self, watchlist_artist):
            return None

    fake_scanner = FakeScanner()
    monkeypatch.setattr("ui.components.watchlist_status_modal.get_watchlist_scanner", lambda spotify: fake_scanner)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    worker = WatchlistScanWorker(spotify_client)
    artist = types.SimpleNamespace(
        artist_name="Fallback Artist",
        spotify_artist_id="spotify-artist",
        itunes_artist_id="111",
        deezer_artist_id="222",
        last_scan_timestamp=None,
    )

    result = worker._scan_artist_with_progress(artist, database=None)

    assert result.success is True
    assert fake_scanner.provider_aware_called is True


def test_watchlist_discography_does_not_fallback_to_spotify_when_primary_provider_is_fallback(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()
    scanner = WatchlistScanner(spotify_client=spotify_client)
    scanner._metadata_service = types.SimpleNamespace(spotify=spotify_client, itunes=fallback_client)

    calls = []

    monkeypatch.setattr(
        scanner,
        "_get_active_client_and_artist_id",
        lambda watchlist_artist: (fallback_client, watchlist_artist.deezer_artist_id, "deezer"),
    )

    def fake_discography(client, artist_id, last_scan_timestamp=None, lookback_days=None):
        calls.append((client, artist_id))
        return []

    monkeypatch.setattr(scanner, "_get_artist_discography_with_client", fake_discography)

    artist = types.SimpleNamespace(
        id=1,
        artist_name="Fallback Artist",
        spotify_artist_id="spotify-artist",
        itunes_artist_id="111",
        deezer_artist_id="222",
        lookback_days=None,
    )

    result = scanner.get_artist_discography_for_watchlist(artist)

    assert result == []
    assert calls == [(fallback_client, "222")]


def test_watchlist_active_client_and_artist_id_supports_discogs(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()
    scanner = WatchlistScanner(spotify_client=spotify_client)

    updated_ids = []
    scanner._metadata_service = types.SimpleNamespace(
        get_active_provider=lambda: "discogs",
        non_spotify=fallback_client,
        spotify=spotify_client,
    )
    scanner._database = types.SimpleNamespace(
        update_watchlist_discogs_id=lambda watchlist_id, discogs_id: updated_ids.append((watchlist_id, discogs_id))
    )

    artist = types.SimpleNamespace(
        id=7,
        artist_name="Discogs Artist",
        spotify_artist_id="spotify-artist",
        itunes_artist_id=None,
        deezer_artist_id=None,
        discogs_artist_id=None,
    )

    client, artist_id, provider = scanner.get_active_client_and_artist_id(artist)

    assert provider == "discogs"
    assert client is fallback_client
    assert artist_id == "222"
    assert updated_ids == [(7, "222")]


def test_legacy_spotify_discography_helper_accepts_lookback_days(monkeypatch):
    spotify_client = SpotifyStub()
    scanner = WatchlistScanner(spotify_client=spotify_client)

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    result = scanner.get_artist_discography("spotify-artist", lookback_days=30)

    assert result == []
    assert spotify_client.artist_album_calls


def test_populate_discovery_pool_uses_primary_client_not_spotify(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()

    class DiscoveryDbStub(WatchlistDbStub):
        def get_top_similar_artists(self, limit=50, profile_id=1):
            return [
                types.SimpleNamespace(
                    id=1,
                    similar_artist_name="Provider Similar",
                    similar_artist_spotify_id="spotify-similar",
                    similar_artist_itunes_id="111",
                    similar_artist_deezer_id="222",
                    occurrence_count=2,
                )
            ]

    scanner = WatchlistScanner(spotify_client=spotify_client)
    scanner._database = DiscoveryDbStub()
    scanner._metadata_service = types.SimpleNamespace(
        get_active_provider=lambda: "deezer",
        _get_client=lambda: fallback_client,
    )

    monkeypatch.setattr(scanner, "cache_discovery_recent_albums", lambda profile_id=1: None)
    monkeypatch.setattr(scanner, "curate_discovery_playlists", lambda profile_id=1: None)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    scanner.populate_discovery_pool(top_artists_limit=1, albums_per_artist=1, profile_id=1)

    assert fallback_client.artist_album_calls
    assert spotify_client.artist_album_calls == []


def test_cache_discovery_recent_albums_skips_spotify_when_primary_provider_is_fallback(monkeypatch):
    fallback_client = FallbackAlbumsClient()
    spotify_client = SpotifyStub()
    database = WatchlistDbStub()

    scanner = WatchlistScanner(spotify_client=spotify_client)
    scanner._database = database
    scanner._metadata_service = types.SimpleNamespace(get_active_provider=lambda: "deezer")

    monkeypatch.setattr("core.watchlist_scanner._get_fallback_metadata_client", lambda: (fallback_client, "deezer"))
    monkeypatch.setattr(scanner, "_get_listening_profile", lambda profile_id=1: {"has_data": False, "avg_daily_plays": 0})
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    scanner.cache_discovery_recent_albums(profile_id=1)

    assert fallback_client.artist_album_calls
    assert spotify_client.artist_album_calls == []
