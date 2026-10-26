import time
from collections import OrderedDict

from backend.models.search import SearchResult


class SearchCache:
    """Bounded process-local TTL cache. Private torrent URLs never reach disk.

    As with MetadataCache's memory tier, values are copied on access; deep
    copies also isolate ranking/deduplication, which mutate SearchResult objects.
    """

    def __init__(
        self,
        ttl: float = 300,
        empty_ttl: float = 20,
        max_entries: int = 256,
        max_results: int = 20000,
    ):
        self.ttl = ttl
        self.empty_ttl = empty_ttl
        self.max_entries = max_entries
        self.max_results = max_results
        self._entries: OrderedDict[str, tuple[float, list[SearchResult]]] = (
            OrderedDict()
        )

    def prune(self) -> None:
        now = time.monotonic()
        for key, (expires, _) in list(self._entries.items()):
            if expires <= now:
                del self._entries[key]

    def get(self, key: str) -> list[SearchResult] | None:
        self.prune()
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return [item.model_copy(deep=True) for item in entry[1]]

    def set(self, key: str, results: list[SearchResult]) -> None:
        self.prune()
        if self.max_entries <= 0 or len(results) > self.max_results:
            return
        ttl = self.ttl if results else self.empty_ttl
        self._entries[key] = (
            time.monotonic() + ttl,
            [item.model_copy(deep=True) for item in results],
        )
        self._entries.move_to_end(key)
        count = sum(len(items) for _, items in self._entries.values())
        while len(self._entries) > self.max_entries or count > self.max_results:
            _, (_, removed) = self._entries.popitem(last=False)
            count -= len(removed)
