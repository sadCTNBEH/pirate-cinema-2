# Linux distribution: Qt, PyQt and media codecs

This notice records the licensing review required before publishing Linux
AppImage or Flatpak artifacts. It is a technical checklist, not a legal opinion
or evidence that Pirate Cinema has obtained a patent or commercial license.

## Current release gate

Do not set `PIRATE_CINEMA_CODEC_REDISTRIBUTION_APPROVED=true` until the person
responsible for distribution has confirmed, for each target country and package,
that the rights below are satisfied. The workflow variable is an explicit human
attestation; it does not grant rights or replace a legal review. The project
uses GNU GPL version 3 (see the root LICENSE), based on the upstream
cyberboy1999/pirate-cinema project. No evidence of a Qt/PyQt commercial license
or H.264/AAC patent-pool license is present in this repository.

## Project license and source obligations

The GPLv3 project license is compatible with PyQt's GPLv3 route, subject to
review of the exact combination and ownership of the rework. Conveying covered
object code requires the complete corresponding source under GPLv3, including
the application source, build/install scripts, and modifications to covered
components. If binaries are conveyed by download, provide recipients an
equivalent no-charge access to the corresponding source from the same place.
When conveying object code in a physical product, GPLv3 section 6 may require
Installation Information for a User Product. The precise obligations depend on
the distribution form; this document does not establish that they are met.
The Linux binary recipes also compile GPL-enabled FFmpeg/x264, which brings
separate corresponding-source and notice obligations for those builds.

## Qt and Qt WebEngine

Qt is distributed under different terms by module and build. Depending on the
selected module/build, open-source Qt is available under LGPLv3 or GPLv3 (some
modules are GPL-only); commercial Qt is a separate option. Qt WebEngine also
contains Chromium and many third-party components, with their own notices and
source obligations. Bundled Qt libraries must ship with the applicable license
texts, notices, and a practical way for recipients to replace/modify LGPL
components where the selected license requires it. Keep the exact source,
configuration, and notices corresponding to each shipped binary.

Official references:

- [Qt licensing](https://doc.qt.io/qt-6/licensing.html)
- [Qt WebEngine licensing and third-party notices](https://doc.qt.io/qt-6/qtwebengine-licensing.html)
- [Qt open-source licensing FAQ](https://www.qt.io/faq/qt-open-source-licensing)

## PyQt6

Riverbank's PyQt6 is offered under GPLv3 or a commercial license; it is not an
LGPL substitute. The AppImage bundles PyQt bindings, and the Flatpak runtime
uses PyQt bindings from the Riverbank PyQt BaseApp. Confirm either that the
complete application distribution complies with the applicable GPLv3 terms
(including source and corresponding-source obligations for all covered work),
or that the required commercial PyQt license has been obtained. Do not infer
PyQt rights from Qt's license.

- [Riverbank PyQt licensing](https://riverbankcomputing.com/software/pyqt/license)

## H.264 / AVC and AAC

The proprietary-codec Qt WebEngine build option enables the codec implementation
in Chromium; it does not grant patent rights. Qt's documentation explicitly
warns distributors to acquire licenses when distributing proprietary codec
libraries. H.264/AVC and AAC patent obligations may depend on the implementation,
distribution model, use, territory, and whether a patent pool's terms apply.
Determine the applicable obligations directly with the relevant licensors and
qualified counsel. No patent-pool or patent license is evidenced in this repo.

- [Qt WebEngine audio/video codec configuration and warning](https://doc.qt.io/qt-6/qtwebengine-features.html#audio-and-video-codecs)
- [Via Licensing AVC licensing program](https://www.via-la.com/licensing-2/avc-h-264/)
- [Via Licensing AAC licensing program](https://www.via-la.com/licensing-2/aac/)

## Before enabling public artifacts

- Record the chosen Qt and PyQt license route and obtain approval from the
  rights holder for the application and any included modifications.
- Publish exact corresponding source archives (including patches and build
  scripts) alongside every covered binary and retain the source for the
  required period.
- Include Qt, Chromium and all bundled dependency notices/source offers required
  by their exact licenses in each package; verify the PyQt GPL/commercial route.
- Obtain a written determination of H.264/AAC patent obligations for the
  territories and distribution model, and secure any required licenses.
- Keep the release variable disabled until these records exist. The Linux
  release workflow also checks real H.264/AAC playback and Chromium's security
  patch level; passing those checks is not a license grant.
