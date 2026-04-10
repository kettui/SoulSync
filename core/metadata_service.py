"""
Metadata Service - unified metadata provider selection.

The app now treats the configured metadata source as the primary provider for
general metadata flows. Legacy "auto" mode is retained, but now resolves to
that configured primary provider rather than implicitly preferring Spotify.
"""

import threading
from typing import List, Optional, Dict, Any, Literal, Tuple
from core.spotify_client import SpotifyClient
from core.itunes_client import iTunesClient
from utils.logging_config import get_logger

logger = get_logger("metadata_service")

MetadataProvider = Literal["spotify", "itunes", "deezer", "discogs", "hydrabase", "auto", "primary"]

_SUPPORTED_METADATA_SOURCES = {"spotify", "itunes", "deezer", "discogs", "hydrabase"}
_DEFAULT_PRIMARY_METADATA_SOURCE = "deezer"
_DEFAULT_NON_SPOTIFY_METADATA_SOURCE = "deezer"


_client_cache_lock = threading.Lock()
_shared_spotify_client: Optional[SpotifyClient] = None
_shared_non_spotify_client: Optional[Any] = None
_shared_non_spotify_source: Optional[str] = None


def _normalize_metadata_source(source: Optional[str], default: str = _DEFAULT_PRIMARY_METADATA_SOURCE) -> str:
    """Normalize a configured metadata source to a supported provider name."""
    source_name = str(source or "").strip().lower()
    if source_name in _SUPPORTED_METADATA_SOURCES:
        return source_name
    return default


def _normalize_primary_metadata_source(source: Optional[str], default: str = _DEFAULT_PRIMARY_METADATA_SOURCE) -> str:
    """Backward-compatible alias for metadata source normalization."""
    return _normalize_metadata_source(source, default=default)


def get_configured_primary_metadata_source(default: str = _DEFAULT_PRIMARY_METADATA_SOURCE) -> str:
    """Get the configured primary metadata source from settings.

    ``metadata.primary_source`` is the canonical setting. The older
    ``metadata.fallback_source`` key is still read as a migration shim for
    existing configs.
    """
    try:
        from config.settings import config_manager
        configured = config_manager.get('metadata.primary_source', None)
        if configured:
            return _normalize_metadata_source(configured, default=default)

        legacy_configured = config_manager.get('metadata.fallback_source', None)
        if legacy_configured:
            return _normalize_metadata_source(legacy_configured, default=default)

        return default
    except Exception:
        return default


def _get_configured_fallback_source():
    """Backward-compatible alias for the configured primary metadata source."""
    return get_configured_primary_metadata_source()


def get_configured_non_spotify_metadata_source(default: str = _DEFAULT_NON_SPOTIFY_METADATA_SOURCE) -> str:
    """Get the configured non-Spotify metadata source used by legacy fallback flows."""
    source = _normalize_metadata_source(get_configured_primary_metadata_source(default=default), default=default)
    return source if source != "spotify" else default


def _create_non_spotify_metadata_client(source: Optional[str] = None):
    """Create the configured non-Spotify metadata client."""
    source = _normalize_metadata_source(source, default=_DEFAULT_NON_SPOTIFY_METADATA_SOURCE) if source is not None else get_configured_non_spotify_metadata_source()
    if source == 'deezer':
        from core.deezer_client import DeezerClient
        return DeezerClient()
    if source == 'discogs':
        try:
            from config.settings import config_manager
            token = config_manager.get('discogs.token', '')
            if token:
                from core.discogs_client import DiscogsClient
                return DiscogsClient(token=token)
        except Exception:
            pass
        return iTunesClient()
    if source == 'hydrabase':
        try:
            from core.hydrabase_client import HydrabaseClient
            # Hydrabase client is managed globally — try to import the running instance
            import importlib
            ws_module = importlib.import_module('web_server')
            client = getattr(ws_module, 'hydrabase_client', None)
            if client and client.is_connected():
                return client
        except Exception:
            pass
        # Hydrabase not available — fall back to iTunes
        return iTunesClient()
    return iTunesClient()


def _create_fallback_client(source: Optional[str] = None):
    """Backward-compatible alias for the legacy non-Spotify metadata client helper."""
    return _create_non_spotify_metadata_client(source)


def _get_shared_spotify_client(refresh: bool = False) -> SpotifyClient:
    """Get the shared Spotify client used by general metadata flows."""
    global _shared_spotify_client
    with _client_cache_lock:
        if refresh or _shared_spotify_client is None:
            _shared_spotify_client = SpotifyClient()
        return _shared_spotify_client


def _get_shared_non_spotify_metadata_client(refresh: bool = False):
    """Get the shared non-Spotify client used by legacy Spotify fallback flows."""
    global _shared_non_spotify_client, _shared_non_spotify_source
    configured_source = get_configured_non_spotify_metadata_source()
    with _client_cache_lock:
        if refresh or _shared_non_spotify_client is None or _shared_non_spotify_source != configured_source:
            _shared_non_spotify_client = _create_non_spotify_metadata_client(configured_source)
            _shared_non_spotify_source = configured_source
        return _shared_non_spotify_client


def _get_shared_fallback_client(refresh: bool = False):
    """Backward-compatible alias for the shared non-Spotify client helper."""
    return _get_shared_non_spotify_metadata_client(refresh=refresh)


def get_metadata_client_for_source(
    source: MetadataProvider,
    spotify_client: Optional[SpotifyClient] = None,
) -> Tuple[Any, str]:
    """Get a metadata client for an explicit provider selection."""
    if source in ("auto", "primary"):
        return get_primary_metadata_client(spotify_client)

    normalized_source = _normalize_metadata_source(source)

    if normalized_source == "spotify":
        client = spotify_client or _get_shared_spotify_client()
        return client, "spotify"
    if normalized_source == "deezer":
        from core.deezer_client import DeezerClient
        return DeezerClient(), "deezer"
    if normalized_source == "discogs":
        try:
            from config.settings import config_manager
            token = config_manager.get('discogs.token', '')
            if token:
                from core.discogs_client import DiscogsClient
                return DiscogsClient(token=token), "discogs"
        except Exception:
            pass
        return iTunesClient(), "itunes"
    if normalized_source == "hydrabase":
        try:
            import importlib
            ws_module = importlib.import_module('web_server')
            client = getattr(ws_module, 'hydrabase_client', None)
            if client and client.is_connected():
                return client, "hydrabase"
        except Exception:
            pass
        return iTunesClient(), "itunes"
    return iTunesClient(), "itunes"


def _infer_provider_from_client(client: Any, spotify_client: Optional[SpotifyClient] = None) -> str:
    """Infer the effective provider name from a metadata client instance."""
    if spotify_client is not None and client is spotify_client:
        return "spotify"
    class_name = client.__class__.__name__.lower()
    if "deezer" in class_name:
        return "deezer"
    if "discogs" in class_name:
        return "discogs"
    if "hydra" in class_name:
        return "hydrabase"
    return "itunes"


def _resolve_primary_metadata_client(spotify_client: Optional[SpotifyClient] = None) -> Tuple[Any, str]:
    """Resolve the effective primary metadata client and provider."""
    configured_source = get_configured_primary_metadata_source()

    if configured_source == "spotify":
        client = spotify_client or _get_shared_spotify_client()
        if client.is_spotify_authenticated():
            return client, "spotify"
        fallback_source = get_configured_non_spotify_metadata_source()
        logger.warning(
            "Configured primary provider is Spotify but Spotify is unavailable; falling back to %s",
            fallback_source,
        )
        fallback_client = _get_shared_non_spotify_metadata_client()
        return fallback_client, _infer_provider_from_client(fallback_client, spotify_client)

    primary_client = _get_shared_non_spotify_metadata_client()
    return primary_client, _infer_provider_from_client(primary_client, spotify_client)


def get_primary_metadata_source(spotify_client: Optional[SpotifyClient] = None) -> str:
    """Get the configured primary metadata provider for general metadata flows."""
    return _resolve_primary_metadata_client(spotify_client)[1]


def get_primary_metadata_client(spotify_client: Optional[SpotifyClient] = None) -> Tuple[Any, str]:
    """Get the client and source name for the configured primary metadata provider."""
    return _resolve_primary_metadata_client(spotify_client)


def log_artist_album_fetch(
    log,
    *,
    feature: str,
    provider: str,
    artist_id: str,
    fetch_mode: str = "active_provider",
    skip_cache: bool = False,
    artist_name: Optional[str] = None,
):
    """Emit a structured log line for artist album fetches."""
    artist_id_str = str(artist_id or "")
    id_kind = "numeric" if artist_id_str.isdigit() else "opaque"
    log.info(
        "artist_album_fetch feature=%s provider=%s fetch_mode=%s id_kind=%s skip_cache=%s artist_id=%s artist_name=%s",
        feature,
        provider,
        fetch_mode,
        id_kind,
        skip_cache,
        artist_id_str,
        artist_name or "",
    )


class MetadataService:
    """
    Unified metadata service for app-wide metadata operations.

    Usage:
        service = MetadataService()
        tracks = service.search_tracks("Radiohead OK Computer")
        # Uses the configured primary metadata provider
    """

    def __init__(
        self,
        preferred_provider: MetadataProvider = "auto",
        spotify_client: Optional[SpotifyClient] = None,
        non_spotify_client: Optional[Any] = None,
        fallback_client: Optional[Any] = None,
    ):
        """
        Initialize metadata service.

        Args:
            preferred_provider: "spotify", "itunes", "deezer", "discogs", "hydrabase", "primary", or "auto" (default)
                - "auto": Use the configured primary metadata provider
                - "spotify": Always use Spotify (may fail if not authenticated)
                - "deezer" / "itunes" / "discogs" / "hydrabase": Always use that explicit provider
                - "primary": Compatibility alias for "auto"
        """
        self.preferred_provider = preferred_provider
        self.spotify = spotify_client or _get_shared_spotify_client()
        self._primary_source = get_configured_primary_metadata_source()
        self.non_spotify = non_spotify_client or fallback_client or _get_shared_non_spotify_metadata_client()
        self.itunes = self.non_spotify  # Backward compatibility for callers/tests that still use .itunes
        self._provider_client_cache: Dict[str, Any] = {}

        self._log_initialization()

    def _log_initialization(self):
        """Log initialization status"""
        spotify_status = "✅ Authenticated" if self.spotify.is_spotify_authenticated() else "❌ Not authenticated"
        fallback_status = "✅ Available" if self.non_spotify.is_authenticated() else "❌ Not available"

        logger.info(f"MetadataService initialized - Spotify: {spotify_status}, configured primary ({self._primary_source.capitalize()}): {fallback_status}")
        logger.info(f"Preferred provider: {self.preferred_provider}")

    def get_active_provider(self) -> str:
        """
        Get the currently active metadata provider.

        Returns:
            The effective provider name for this service instance
        """
        _client, provider = self._resolve_client_and_provider()
        return provider

    def _get_explicit_provider_client(self, provider: str):
        """Get or create a client for an explicit provider override."""
        if provider == "spotify":
            return self.spotify

        cached = self._provider_client_cache.get(provider)
        if cached is None:
            cached, _resolved_provider = get_metadata_client_for_source(provider, spotify_client=self.spotify)
            self._provider_client_cache[provider] = cached
        return cached

    def _resolve_configured_provider(self) -> str:
        """Resolve the configured provider name for this service instance."""
        if self.preferred_provider in ("primary", "auto"):
            return get_primary_metadata_source(self.spotify)
        if self.preferred_provider in _SUPPORTED_METADATA_SOURCES:
            return self.preferred_provider

        logger.warning(
            "Unknown preferred provider '%s', using configured primary provider",
            self.preferred_provider,
        )
        return get_primary_metadata_source(self.spotify)

    def _resolve_client_and_provider(self) -> Tuple[Any, str]:
        """Resolve the effective metadata client and provider for this service instance."""
        provider = self._resolve_configured_provider()

        if provider == "spotify":
            if not self.spotify.is_spotify_authenticated():
                fallback_source = get_configured_non_spotify_metadata_source()
                logger.warning(
                    "Spotify requested but not authenticated, falling back to %s",
                    fallback_source,
                )
                return self.non_spotify, _infer_provider_from_client(self.non_spotify, self.spotify)
            return self.spotify, "spotify"

        if self.preferred_provider in ("primary", "auto"):
            return get_primary_metadata_client(self.spotify)

        return self._get_explicit_provider_client(provider), provider

    def _get_client(self):
        """Get the appropriate client based on provider selection"""
        client, _provider = self._resolve_client_and_provider()
        return client
    
    # ==================== Search Methods ====================
    
    def search_tracks(self, query: str, limit: int = 20) -> List:
        """
        Search for tracks using active provider.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of Track objects
        """
        client = self._get_client()
        provider = self.get_active_provider()
        logger.debug(f"Searching tracks with {provider}: '{query}'")
        return client.search_tracks(query, limit)
    
    def search_artists(self, query: str, limit: int = 20) -> List:
        """
        Search for artists using active provider.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of Artist objects
        """
        client = self._get_client()
        provider = self.get_active_provider()
        logger.debug(f"Searching artists with {provider}: '{query}'")
        return client.search_artists(query, limit)
    
    def search_albums(self, query: str, limit: int = 20) -> List:
        """
        Search for albums using active provider.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of Album objects
        """
        client = self._get_client()
        provider = self.get_active_provider()
        logger.debug(f"Searching albums with {provider}: '{query}'")
        return client.search_albums(query, limit)
    
    # ==================== Detail Fetching ====================
    
    def get_track_details(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed track information"""
        client = self._get_client()
        return client.get_track_details(track_id)
    
    def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album information"""
        client = self._get_client()
        return client.get_album(album_id)
    
    def get_album_tracks(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get all tracks from an album"""
        client = self._get_client()
        provider = self.get_active_provider()
        logger.debug(f"Fetching album tracks with {provider}: {album_id}")
        return client.get_album_tracks(album_id)
    
    def get_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get artist information"""
        client = self._get_client()
        return client.get_artist(artist_id)
    
    def get_artist_albums(self, artist_id: str, album_type: str = "album,single", limit: int = 50) -> List:
        """Get artist's albums/discography"""
        client = self._get_client()
        provider = self.get_active_provider()
        logger.debug(f"Fetching artist albums with {provider}: {artist_id}")
        return client.get_artist_albums(artist_id, album_type, limit)
    
    def get_track_features(self, track_id: str) -> Optional[Dict[str, Any]]:
        """
        Get track audio features (Spotify only).
        Returns None for iTunes.
        """
        client = self._get_client()
        return client.get_track_features(track_id)
    
    # ==================== User Library (Spotify only) ====================
    
    def get_user_playlists(self) -> List:
        """Get user playlists (Spotify only)"""
        if self.spotify.is_spotify_authenticated():
            return self.spotify.get_user_playlists()
        logger.warning("User playlists only available with Spotify authentication")
        return []

    def get_saved_tracks(self) -> List:
        """Get user's saved/liked tracks (Spotify only)"""
        if self.spotify.is_spotify_authenticated():
            return self.spotify.get_saved_tracks()
        logger.warning("Saved tracks only available with Spotify authentication")
        return []

    def get_saved_tracks_count(self) -> int:
        """Get count of user's saved tracks (Spotify only)"""
        if self.spotify.is_spotify_authenticated():
            return self.spotify.get_saved_tracks_count()
        return 0

    # ==================== Utility Methods ====================

    def is_authenticated(self) -> bool:
        """Check if any provider is available"""
        return self.spotify.is_spotify_authenticated() or self.non_spotify.is_authenticated()

    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about available providers"""
        return {
            "active_provider": self.get_active_provider(),
            "spotify_authenticated": self.spotify.is_spotify_authenticated(),
            "non_spotify_available": self.non_spotify.is_authenticated(),
            "itunes_available": self.non_spotify.is_authenticated(),
            "non_spotify_source": get_configured_non_spotify_metadata_source(),
            "primary_source": get_primary_metadata_source(self.spotify),
            "fallback_source": get_configured_non_spotify_metadata_source(),
            "preferred_provider": self.preferred_provider,
            "can_access_user_data": self.spotify.is_spotify_authenticated(),
        }
    
    def reload_config(self):
        """Reload configuration for both clients"""
        logger.info("Reloading metadata service configuration")
        self.spotify.reload_config()
        self._provider_client_cache = {}
        # Re-create the shared non-Spotify client in case the configured primary changed
        new_source = get_configured_primary_metadata_source()
        if new_source != self._primary_source:
            self._primary_source = new_source
            self.non_spotify = _get_shared_non_spotify_metadata_client(refresh=True)
            self.itunes = self.non_spotify
        elif hasattr(self.non_spotify, 'reload_config'):
            self.non_spotify.reload_config()
        self._log_initialization()


# Convenience singleton instance
_metadata_service_instance: Optional[MetadataService] = None


def get_metadata_service() -> MetadataService:
    """
    Get global metadata service instance (singleton pattern).
    
    Returns:
        MetadataService instance
    """
    global _metadata_service_instance
    if _metadata_service_instance is None:
        _metadata_service_instance = MetadataService()
    return _metadata_service_instance
