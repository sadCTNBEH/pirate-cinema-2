"""Conservative track identity matching and one-shot selection for a loaded file."""

import re
import threading
import time
import unicodedata

LANGUAGES = {"ru": "ru", "rus": "ru", "russian": "ru", "русский": "ru",
             "en": "en", "eng": "en", "english": "en", "английский": "en"}
STUDIOS = {"lostfilm": ("lostfilm", "лостфильм", "lost film"),
           "newstudio": ("newstudio", "new studio", "ньюстудио"),
           "kubik": ("кубик в кубе", "kubik v kube"),
           "alexfilm": ("alexfilm", "alex film"), "jaskier": ("jaskier", "яскер"),
           "hdrezka": ("hdrezka", "hd rezka"), "tvshows": ("tvshows", "tv shows"),
           "baibako": ("baibako", "байбако"), "ams": ("ams", "амс")}
FLAGS = ("forced", "hearing-impaired", "visual-impaired", "commentary")


def language(value):
    code = str(value or "").strip().casefold().replace("_", "-")
    return LANGUAGES.get(code, LANGUAGES.get(code.split("-")[0], code.split("-")[0]))


def title(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    value = re.sub(r"\b(?:aac|ac3|eac3|dts(?:hd)?|truehd|flac|opus|mp3|pcm|rus|russian|eng|english|русский|английский)\b", " ", value)
    value = re.sub(r"\b\d+(?:[.,]\d+)?(?:\s*(?:kbps|kbit|khz|канал\w*|ch))?\b", " ", value)
    return " ".join(re.findall(r"[^\W_]+", value, re.UNICODE))[:200]


def identity(track):
    name = title(track.get("title"))
    if name and all(token in {"audio", "track", "dub", "dubbing", "mvo", "dvo", "avo", "дубляж", "дублированный", "аудио", "озвучка", "дорожка", "основная"} for token in name.split()):
        name = ""
    descriptive_flags = {"forced": r"\b(?:forced|форсированные|форс)\b",
                         "commentary": r"\b(?:commentary|комментарии|комментарий)\b",
                         "hearing-impaired": r"\b(?:sdh|hearing impaired)\b",
                         "visual-impaired": r"\b(?:audio description|тифлокомментарий)\b"}
    studio = next((key for key, aliases in STUDIOS.items()
                   if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", name) for alias in aliases)), "")
    return {"lang": language(track.get("lang")), "title": name, "studio": studio,
            "codec": str(track.get("codec") or "").casefold()[:40],
            "channels": str(track.get("audio-channels") or track.get("demux-channel-count") or "")[:24],
            **{flag: track.get(flag) is True or bool(re.search(descriptive_flags[flag], name)) for flag in FLAGS}}


def match_track(tracks, remembered):
    """A studio/title is evidence; language and codec alone cannot identify a voice."""
    if not isinstance(remembered, dict) or not (remembered.get("studio") or remembered.get("title")):
        return None
    ranked = []
    for track in tracks:
        candidate = identity(track)
        if remembered.get("lang") and candidate["lang"] != language(remembered["lang"]):
            continue
        if any(bool(remembered.get(flag)) != candidate[flag] for flag in FLAGS):
            continue
        if remembered.get("studio"):
            if candidate["studio"] != remembered["studio"]:
                continue
        elif candidate["title"] != remembered["title"]:
            continue
        score = 100 if candidate["title"] == remembered.get("title") else 80
        score += 4 if candidate["codec"] and candidate["codec"] == remembered.get("codec") else 0
        score += 2 if candidate["channels"] and candidate["channels"] == remembered.get("channels") else 0
        ranked.append((score, track))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]["id"]


def selection(value):
    if value is False or value in (0, "0", "no", "off"):
        return "no"
    return str(value)


def priorities(values, kind):
    allowed = {"ru", "en", "original", "auto"} if kind == "audio" else {"ru", "en", "auto", "off"}
    result = []
    for value in values if isinstance(values, list) else ["auto"]:
        value = language(value)
        if value in allowed and value not in result:
            result.append(value)
            if value in ("auto", "off"):
                break
    return result or ["auto"]


def preferred_track(tracks, order):
    for lang in order:
        if lang == "off":
            return "no"
        if lang == "auto":
            return None
        candidates = [track for track in tracks if (track.get("original") is True if lang == "original" else language(track.get("lang")) == lang)
                      and not any(identity(track)[flag] for flag in FLAGS)]
        if len(candidates) == 1:
            return candidates[0]["id"]
        if candidates:
            # Leave multiple tracks in the preferred language to MPV's default policy.
            return None
    return None


class TrackSelection:
    def __init__(self, send, remember):
        self.send, self.remember = send, remember
        self.lock = threading.RLock()
        self.timer = None
        self.generation = 0
        self.configure({})

    def configure(self, prefs, explicit_audio=None, explicit_sub=None):
        with self.lock:
            self.close()
            self.generation += 1
            self.saved = dict(prefs.get("track_preferences") or {})
            self.orders = {kind: priorities(prefs.get(f"{kind}_languages", ["auto"]), kind) for kind in ("audio", "subtitle")}
            self.explicit = {"audio": explicit_audio, "sub": explicit_sub}
            self.manual = set()
            self.done = set()
            self.expected = {}
            self.values = {}
            self.tracks = []
            self.loaded = False
            self.accepting = False
            self.deadline = 0
            self.pending_manual = {}
            self.requested = {}
            self.configured = True

    def options(self):
        options = {}
        for kind, prop, language_prop in (("audio", "aid", "alang"), ("sub", "sid", "slang")):
            order = self.orders["audio" if kind == "audio" else "subtitle"]
            codes = [code for lang in order for code in ({"ru": ["ru", "rus"], "en": ["en", "eng"]}.get(lang, []))]
            options[language_prop] = ",".join(codes)
            choice = self.saved.get(kind, {})
            explicit = self.explicit[kind]
            if kind in self.requested:
                options[prop] = selection(self.requested[kind])
                continue
            if explicit is not None:
                options[prop] = str(explicit) if explicit else "no"
                self.manual.add(kind)
                self.pending_manual[kind] = explicit or "no"
            else:
                options[prop] = "no" if kind == "sub" and (order == ["off"] or choice.get("mode") == "off") else "auto"
        return options

    def start(self):
        with self.lock:
            self.close()
            self.generation += 1
            self.tracks = []
            self.values = {}
            self.expected = {}
            self.done = set()
            if not self.configured:
                self.explicit = {"audio": None, "sub": None}
                self.manual = set()
                self.pending_manual = {}
                self.requested = {}
            self.configured = False
            self.loaded = False
            self.accepting = True

    def event(self, name, value=None):
        with self.lock:
            if name == "start-file":
                self.start()
                return
            if name == "end-file":
                self.loaded = self.accepting = False
                self.close()
                return
            if not self.accepting:
                return
            if name == "file-loaded":
                self.loaded = True
                self.deadline = time.monotonic() + 3
            elif name == "track-list":
                self.tracks = [dict(track) for track in value if isinstance(track, dict) and track.get("id") is not None] if isinstance(value, list) else []
                for kind, selected in list(self.pending_manual.items()):
                    self._remember(kind, selected)
            elif name in ("aid", "sid"):
                kind = "audio" if name == "aid" else "sub"
                old = self.values.get(kind)
                self.values[kind] = value
                expected = self.expected.get(kind)
                if expected is not None and selection(expected) == selection(value):
                    self.expected.pop(kind, None)
                elif self.loaded and value is not None and old is not None and selection(old) != selection(value):
                    # Native MPV keyboard/OSC changes bypass the application API.
                    self.manual.add(kind)
                    self._remember(kind, value)
                return
            if self.loaded:
                for kind, selected in list(self.requested.items()):
                    if selection(selected) not in ("no", "auto") and not any(track.get("type") == kind and str(track["id"]) == str(selected) for track in self.tracks):
                        continue
                    self.requested.pop(kind, None)
                    if selection(self.values.get(kind)) != selection(selected):
                        self.expected[kind] = selected
                        self.send(["set_property", "aid" if kind == "audio" else "sid", selected])
            if self.loaded and any(kind not in self.done | self.manual for kind in ("audio", "sub")):
                self._schedule()

    def _schedule(self):
        self.close()
        generation = self.generation
        delay = min(0.25, max(0.01, self.deadline - time.monotonic()))
        self.timer = threading.Timer(delay, lambda: self.apply(generation))
        self.timer.daemon = True
        self.timer.start()

    def apply(self, generation=None):
        with self.lock:
            if not self.loaded or (generation is not None and generation != self.generation):
                return
            for kind, prop in (("audio", "aid"), ("sub", "sid")):
                if kind in self.manual or kind in self.done:
                    continue
                saved = self.saved.get(kind, {})
                order = self.orders["audio" if kind == "audio" else "subtitle"]
                if order == ["auto"] and not saved:
                    self.done.add(kind)
                    continue
                chosen = "no" if kind == "sub" and (order == ["off"] or saved.get("mode") == "off") else None
                tracks = [track for track in self.tracks if track.get("type") == kind]
                if not tracks and chosen is None and time.monotonic() < self.deadline:
                    continue
                self.done.add(kind)
                if chosen is None and saved.get("mode") != "auto":
                    chosen = match_track(tracks, saved)
                    if chosen is None and (saved.get("studio") or saved.get("title")) and time.monotonic() < self.deadline:
                        self.done.discard(kind)
                        continue
                if chosen is None:
                    chosen = preferred_track(tracks, order)
                if chosen is not None and selection(self.values.get(kind)) != selection(chosen):
                    self.expected[kind] = chosen
                    self.send(["set_property", prop, chosen])
            if any(kind not in self.done | self.manual for kind in ("audio", "sub")) and time.monotonic() < self.deadline:
                self._schedule()

    def manual_command(self, command):
        if len(command) < 2 or command[0] not in ("set_property", "cycle", "add") or command[1] not in ("aid", "sid"):
            return
        with self.lock:
            kind = "audio" if command[1] == "aid" else "sub"
            self.manual.add(kind)
            self.expected.pop(kind, None)
            if command[0] == "set_property" and len(command) >= 3:
                if not self.loaded:
                    self.requested[kind] = command[2]
                self._remember(kind, command[2])

    def _remember(self, kind, selected):
        if selected in (False, 0, "no", "off"):
            choice = {"mode": "off"} if kind == "sub" else {"mode": "auto"}
        elif selected == "auto":
            choice = {"mode": "auto"}
        else:
            track = next((track for track in self.tracks if track.get("type") == kind and str(track["id"]) == str(selected)), None)
            if not track:
                self.pending_manual[kind] = selected
                return
            choice = {"mode": "track", **identity(track)}
        self.pending_manual.pop(kind, None)
        if self.saved.get(kind) != choice:
            self.saved[kind] = choice
            self.remember({kind: choice})

    def close(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
