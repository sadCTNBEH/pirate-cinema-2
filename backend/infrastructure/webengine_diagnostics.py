"""Runtime diagnostics for the Qt WebEngine used by the native application."""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


KODIK_HOST = re.compile(r"(^|\.)kodik(player)?\.(com|info|biz|cc)$", re.IGNORECASE)
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

KODIK_SCRIPT = r"""(() => {
  if (!/(^|\.)kodik(player)?\.(com|info|biz|cc)$/i.test(location.hostname)) return;
  if (window.__pcKodikDiagnosticsInstalled) return;
  window.__pcKodikDiagnosticsInstalled = true;
  const safeUrl = value => {
    try {
      const u = new URL(value, location.href);
      const parts = u.pathname.split('/').map((part, i) =>
        (i > 1 && /^[a-z0-9_-]{18,}$/i.test(part)) ? '<redacted>' : part);
      return {origin: u.origin, path: parts.join('/'), queryKeys: [...u.searchParams.keys()]};
    } catch { return {origin: location.origin, path: '<unavailable>', queryKeys: []}; }
  };
  const send = (kind, data={}) => {
    const row = {kind, url: safeUrl(location.href), at: Math.round(performance.now()), ...data};
    console.warn('[PC-KODIK-DIAG] ' + JSON.stringify(row));
    try { window.parent.postMessage({type:'pc-kodik-diagnostic', detail:row}, '*'); } catch {}
  };
  const mediaUrl = value => /\.(m3u8|mpd|mp4|m4s|ts|aac|m4a|webm|vtt|mp3)(?:$|[?#])/i.test(value) ||
    /\b(segment|chunk|manifest|playlist|videoplayback)\b/i.test(value);
  const adUrl = value => /(serving-sys\.ru|\/adserver(?:[./?]|$)|\/vast(?:[./?]|$)|\/ads?(?:[./?]|$))/i.test(value);
  const videoState = v => {
    let buffered=[]; try { for(let i=0;i<v.buffered.length;i++) buffered.push([+v.buffered.start(i).toFixed(2),+v.buffered.end(i).toFixed(2)]); } catch {}
    let seekable=[]; try { for(let i=0;i<v.seekable.length;i++) seekable.push([+v.seekable.start(i).toFixed(2),+v.seekable.end(i).toFixed(2)]); } catch {}
    const quality = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
    const source = v.currentSrc || v.getAttribute('src') || '';
    return {src:source ? safeUrl(source) : null, hasSource:!!(source || v.srcObject), currentTime:+v.currentTime.toFixed(2), duration:Number.isFinite(v.duration)?+v.duration.toFixed(2):null,
      paused:v.paused, ended:v.ended, seeking:v.seeking, muted:v.muted, volume:v.volume, readyState:v.readyState, networkState:v.networkState,
      videoWidth:v.videoWidth, videoHeight:v.videoHeight, buffered, seekable,
      error:v.error?{code:v.error.code,message:v.error.message||''}:null,
      totalVideoFrames:quality?.totalVideoFrames ?? null, droppedVideoFrames:quality?.droppedVideoFrames ?? null,
      audioTracks:v.audioTracks?.length ?? null, audioDecodedBytes:v.webkitAudioDecodedByteCount ?? null};
  };
  const attachVideo = v => {
    if (v.__pcKodikObserved) return; v.__pcKodikObserved=true;
    let priorTime=v.currentTime, priorFrames=v.getVideoPlaybackQuality?v.getVideoPlaybackQuality().totalVideoFrames:null;
    const snapshot = event => {
      const state=videoState(v);
      if(event==='state'){
        const frames=state.totalVideoFrames;
        const framesChanged=frames===null||priorFrames===null?null:frames>priorFrames;
        const timeAdvanced=state.currentTime-priorTime>=0.15;
        const confirmed=!state.paused&&!state.seeking&&!state.ended&&!state.error&&state.readyState>=2&&state.videoWidth>0&&state.videoHeight>0&&timeAdvanced&&(framesChanged!==false);
        send('video-state',{...state,timeAdvanced,framesChanged,confirmed});
        priorTime=state.currentTime;priorFrames=frames;
      } else send('video-'+event,state);
    };
    for (const event of ['loadedmetadata','loadeddata','canplay','playing','pause','waiting','stalled','suspend','seeking','seeked','ended','error','emptied'])
      v.addEventListener(event, () => snapshot(event));
    snapshot('found');
    let last=0;
    const tick=()=>{ if(!v.isConnected)return; const now=performance.now(); if(now-last>2500){last=now;snapshot('state');} setTimeout(tick,500); };
    setTimeout(tick,500);
  };
  document.querySelectorAll('video').forEach(attachVideo);
  new MutationObserver(records=>{
    for(const r of records) for(const n of r.addedNodes) {
      if(n.nodeType!==1) continue;
      if(n.matches?.('video')) attachVideo(n);
      n.querySelectorAll?.('video').forEach(attachVideo);
    }
  }).observe(document,{childList:true,subtree:true});
  if (window.MediaSource) {
    const originalSupported=MediaSource.isTypeSupported.bind(MediaSource);
    MediaSource.isTypeSupported=(type)=>{ const ok=originalSupported(type); if(/(mp4|avc|h264|aac|mpeg)/i.test(type))send('mse-type',{type, supported:ok}); return ok; };
    const originalAdd=MediaSource.prototype.addSourceBuffer;
    MediaSource.prototype.addSourceBuffer=function(type){
      send('sourcebuffer-add',{mime:type}); const b=originalAdd.call(this,type);
      b.addEventListener('updateend',()=>{let ranges=[];try{for(let i=0;i<b.buffered.length;i++)ranges.push([+b.buffered.start(i).toFixed(2),+b.buffered.end(i).toFixed(2)]);}catch{}send('sourcebuffer-updateend',{mime:type,buffered:ranges});});
      b.addEventListener('error',()=>send('sourcebuffer-error',{mime:type}));
      return b;
    };
  }
  const OriginalXHR=window.XMLHttpRequest;
  window.XMLHttpRequest=function(){
    const x=new OriginalXHR(); let requestUrl='';
    const open=x.open; x.open=function(method,url,...args){requestUrl=String(url);return open.call(this,method,url,...args);};
    x.addEventListener('loadend',()=>{const host=safeUrl(requestUrl).origin;if(!adUrl(requestUrl)&&(mediaUrl(requestUrl)||x.status>=400))send('xhr-response',{status:x.status,statusText:x.statusText,url:safeUrl(requestUrl),host});});
    x.addEventListener('error',()=>{if(!adUrl(requestUrl)&&mediaUrl(requestUrl))send('xhr-error',{url:safeUrl(requestUrl)});});
    return x;
  };
  window.XMLHttpRequest.prototype=OriginalXHR.prototype;
  Object.setPrototypeOf(window.XMLHttpRequest,OriginalXHR);
  window.fetch=(original=>function(input,init){const target=typeof input==='string'?input:(input?.url||'');return original.call(this,input,init).then(response=>{if(!adUrl(target)&&(mediaUrl(target)||response.status>=400))send('fetch-response',{status:response.status,statusText:response.statusText,url:safeUrl(target)});return response;},error=>{if(!adUrl(target)&&mediaUrl(target))send('fetch-error',{url:safeUrl(target),error:String(error)});throw error;});})(window.fetch);
  try { new PerformanceObserver(list=>list.getEntries().forEach(e=>{if(!adUrl(e.name)&&mediaUrl(e.name))send('resource-timing',{url:safeUrl(e.name),initiatorType:e.initiatorType,responseStatus:e.responseStatus??null,transferSize:e.transferSize??null,duration:+e.duration.toFixed(1)});})).observe({type:'resource',buffered:true}); } catch {}
  const flashNotice=()=>{const text=(document.body?.innerText||'').slice(0,4000);if(/unsupported video format|install adobe flash|неподдерживаемый формат видео|установить adobe flash/i.test(text))send('flash-fallback-visible',{text:text.match(/.{0,70}(?:unsupported video format|install adobe flash|неподдерживаемый формат видео|установить adobe flash).{0,100}/i)?.[0]||''});};
  new MutationObserver(flashNotice).observe(document,{childList:true,subtree:true,characterData:true});
  send('frame-ready',{userAgent:navigator.userAgent,visibility:document.visibilityState}); flashNotice();
})();"""


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        parts = [part if len(part) < 20 else "<redacted>" for part in parsed.path.split("/")]
        query_names = ",".join(sorted({part.partition("=")[0] for part in parsed.query.split("&") if part}))
        return f"{parsed.scheme}://{parsed.netloc}{'/'.join(parts)}" + (f"?keys={query_names}" if query_names else "")
    except (TypeError, ValueError):
        return "<invalid-url>"


def _redact_urls(value: str) -> str:
    return URL_IN_TEXT.sub(lambda match: _safe_url(match.group(0).rstrip(").,;:")), value)


def _enum_name(value: object) -> str:
    return str(getattr(value, "name", value))


def _is_kodik_url(value: str) -> bool:
    try:
        return bool(KODIK_HOST.search(urlsplit(value).hostname or ""))
    except ValueError:
        return False


def _is_ad_url(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in ("serving-sys.ru", "/adserver", "/vast", "/ads/", "/ad/"))


def _qt_processes() -> list[str]:
    if not sys.platform.startswith("linux") or not Path("/proc/self/maps").is_file():
        return []
    processes: list[str] = []
    parents: dict[int, int] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            match = re.search(r"^PPid:\s+(\d+)$", (proc / "status").read_text(), re.MULTILINE)
            if match:
                parents[int(proc.name)] = int(match[1])
        except (OSError, UnicodeError):
            continue
    for pid, parent in parents.items():
        while parent and parent != os.getpid():
            parent = parents.get(parent, 0)
        if parent != os.getpid():
            continue
        try:
            executable = os.readlink(f"/proc/{pid}/exe")
            if Path(executable).name == "QtWebEngineProcess":
                processes.append(f"pid={pid} exe={executable}")
        except OSError:
            continue
    return processes


def _loaded_qt_libraries() -> list[str]:
    try:
        paths = set()
        for line in Path("/proc/self/maps").read_text(errors="replace").splitlines():
            if "libQt6" in line and ".so" in line:
                path = line.rsplit(maxsplit=1)[-1]
                if path.startswith("/"):
                    paths.add(path.removesuffix(" (deleted)"))
        return sorted(paths)
    except OSError:
        return []


def install_qt_webengine_diagnostics(log: logging.Logger) -> bool:
    """Instrument pywebview's actual Qt page and its profile without changing policy."""
    try:
        import webview.platforms.qt as qt
        from qtpy import QtCore, QtWebEngineCore
        from qtpy.QtWebEngineCore import QWebEngineScript
    except (ImportError, OSError) as error:
        log.warning("[WEBENGINE] Runtime diagnostics unavailable: %s", error)
        return False

    if not getattr(qt, "is_webengine", False):
        log.error("[WEBENGINE] pywebview selected %s, not Qt WebEngine", getattr(qt, "renderer", "unknown"))
        return False

    from backend.core.settings import get_data_dir

    # pywebview reads storage_path at import time. We import the Qt backend
    # early, so select its profile path before any QWebEngineProfile is created.
    # Keep older Chromium releases from opening a newer Qt profile.
    runtime = os.environ.get("PIRATE_CINEMA_QT_RUNTIME_SELECTED", "unknown")
    qt._profile_storage_path = str(get_data_dir() / "qt-webengine" / runtime)
    page_class = qt.BrowserView.WebPage
    original_page_init = page_class.__init__

    def report_main_engine(self, ok):
        if not ok or self._pc_capability_reported:
            return
        self._pc_capability_reported = True
        from PyQt6.QtCore import PYQT_VERSION_STR, QLibraryInfo
        from PyQt6 import QtWebEngineCore as engine

        paths = {
            item.name: QLibraryInfo.path(item)
            for item in QLibraryInfo.LibraryPath
            if item.name in {"PrefixPath", "LibrariesPath", "LibraryExecutablesPath", "PluginsPath", "DataPath"}
        }
        configured_process = os.environ.get("QTWEBENGINEPROCESS_PATH")
        process_candidates = ([Path(configured_process)] if configured_process else []) + [
            Path(paths.get("LibraryExecutablesPath", "")) / "QtWebEngineProcess",
            Path(paths.get("PrefixPath", "")) / "libexec/QtWebEngineProcess",
            Path(paths.get("PrefixPath", "")) / "QtWebEngineProcess",
            Path("/usr/lib/qt6/QtWebEngineProcess"),
            Path("/usr/lib/qt6/libexec/QtWebEngineProcess"),
            Path("/usr/lib/x86_64-linux-gnu/qt6/libexec/QtWebEngineProcess"),
        ]
        process_path = next(
            (str(path.resolve()) for path in process_candidates if path.is_file()),
            "not-found-before-render",
        )
        pyqt = sys.modules.get("PyQt6")
        webengine_extension = sys.modules.get("PyQt6.QtWebEngineCore")
        log.info(
            "[WEBENGINE] runtime=%s pyqt=%s pyqt_path=%s qt_compiled=%s qt_runtime=%s "
            "qtwebengine_binding=%s qtwebengine_extension=%s qtwebengine_version=%s chromium=%s "
            "chromium_security_patch=%s QtWebEngineProcess=%s "
            "QtPaths=%s loadedQtLibraries=%s childProcesses=%s",
            os.environ.get("PIRATE_CINEMA_QT_RUNTIME_SELECTED", "unknown"),
            PYQT_VERSION_STR,
            getattr(pyqt, "__file__", "unknown"),
            getattr(QtCore, "QT_VERSION_STR", getattr(QtCore, "__version__", "unknown")),
            QtCore.qVersion(),
            getattr(QtWebEngineCore, "__file__", "unknown"),
            getattr(webengine_extension, "__file__", "unknown"),
            getattr(engine, "qWebEngineVersion", lambda: "unavailable")(),
            getattr(engine, "qWebEngineChromiumVersion", lambda: "unavailable")(),
            getattr(engine, "qWebEngineChromiumSecurityPatchVersion", lambda: "unavailable")(),
            process_path,
            paths,
            _loaded_qt_libraries(),
            _qt_processes(),
        )

        profile = self.profile()
        settings = profile.settings()
        setting_names = (
            "JavascriptEnabled",
            "PlaybackRequiresUserGesture",
            "LocalContentCanAccessRemoteUrls",
            "LocalContentCanAccessFileUrls",
            "WebGLEnabled",
            "AllowRunningInsecureContent",
        )
        setting_values = {}
        for name in setting_names:
            attribute = getattr(qt.QWebEngineSettings.WebAttribute, name, None)
            if attribute is not None:
                try:
                    setting_values[name] = settings.testAttribute(attribute)
                except (AttributeError, RuntimeError):
                    setting_values[name] = "unavailable"
        log.info(
            "[WEBENGINE] profile=%s persistentStorage=%s cookiesPolicy=%s profileUserAgent=%s settings=%s",
            profile.storageName(),
            profile.persistentStoragePath(),
            _enum_name(profile.persistentCookiesPolicy()),
            profile.httpUserAgent(),
            setting_values,
        )
        self.runJavaScript(
            """(() => {const v=document.createElement('video');
            const types=['video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"',
              'video/mp4; codecs=\"avc1.640028, mp4a.40.2\"',
              'video/mp4; codecs=\"mp4a.40.2\"'];
            return {href:location.origin,ua:navigator.userAgent,canPlay:Object.fromEntries(types.map(t=>[t,v.canPlayType(t)])),
              mse:typeof MediaSource==='undefined'?false:Object.fromEntries(types.map(t=>[t,MediaSource.isTypeSupported(t)])),
              top:window===window.top,iframeCount:document.querySelectorAll('iframe').length};})()""",
            lambda result: log.info("[WEBENGINE][MAIN-WINDOW] codecProbe=%s", result),
        )

    def guarded_report_main_engine(self, ok):
        try:
            report_main_engine(self, ok)
        except Exception:
            log.exception("[WEBENGINE] Could not collect main-window Qt diagnostics")

    def diagnostic_page_init(self, *args, **kwargs):
        original_page_init(self, *args, **kwargs)
        self._pc_capability_reported = False
        script = QWebEngineScript()
        script.setName("pirate-cinema-kodik-media-diagnostics")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(KODIK_SCRIPT)
        self.scripts().insert(script)
        self.loadFinished.connect(self._pc_report_main_engine)

    def diagnostic_console(self, level, message, line_number, source_id):
        raw_text = str(message)
        text = _redact_urls(raw_text)
        if not _is_ad_url(raw_text) and ("[PC-KODIK-DIAG]" in text or re.search(
            r"(CORS|Access to fetch|Failed to load resource|net::ERR_|MEDIA_ERR|MediaError|SourceBuffer|unsupported|SSL|certificate|SyntaxError|Uncaught|NotSupportedError)",
            text,
            re.IGNORECASE,
        )):
            log.warning(
                "[WEBENGINE][CONSOLE] level=%s source=%s line=%s message=%s",
                _enum_name(level),
                _safe_url(str(source_id)),
                line_number,
                text[:1400],
            )
        return super(page_class, self).javaScriptConsoleMessage(level, message, line_number, source_id)

    page_class.__init__ = diagnostic_page_init
    page_class._pc_report_main_engine = guarded_report_main_engine
    page_class.javaScriptConsoleMessage = diagnostic_console

    interceptor = qt.BrowserView.RequestInterceptor
    original_intercept = interceptor.interceptRequest

    def diagnostic_intercept(self, info):
        request = info.requestUrl().toString()
        first_party = info.firstPartyUrl().toString()
        resource_type = _enum_name(info.resourceType())
        media_request = "Media" in resource_type or bool(
            re.search(r"(\.(m3u8|mpd|mp4|m4s|ts|aac|m4a|webm|vtt)(?:$|[?#])|segment|chunk)", request, re.IGNORECASE)
        )
        if not _is_ad_url(request) and (
            _is_kodik_url(request) or (_is_kodik_url(first_party) and media_request)
        ):
            try:
                headers = {
                    key.data().decode("utf-8", errors="replace").lower(): value.data().decode("utf-8", errors="replace")
                    for key, value in info.httpHeaders().items()
                }
            except (AttributeError, RuntimeError, TypeError):
                headers = {}
            log.info(
                "[WEBENGINE][REQUEST] type=%s method=%s url=%s firstParty=%s referer=%s cookiePresent=%s",
                resource_type,
                bytes(info.requestMethod()).decode("ascii", errors="replace"),
                _safe_url(request),
                _safe_url(first_party),
                _safe_url(headers["referer"]) if headers.get("referer") else "absent",
                bool(headers.get("cookie")),
            )
        return original_intercept(self, info)

    interceptor.interceptRequest = diagnostic_intercept
    os.environ["PIRATE_CINEMA_KODIK_MEDIA_DIAGNOSTICS"] = "1"
    log.info("[WEBENGINE] In-process Qt WebEngine media diagnostics installed on pywebview's main profile")
    return True
