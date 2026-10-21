#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build build/TYTcps-<version>-x86_64.AppImage from this checkout (make appimage).
#
# A portable Python (python-appimage's manylinux build) with PyQt6 from
# PyPI, whose wheels carry Qt, plus TYTcps and its engine. Downloads are
# pinned and kept in build/appimage-cache; a download whose checksum doesn't
# match is refused. The engine is built on this machine, so the AppImage
# runs on systems with this machine's glibc or newer: release builds come
# from CI on an older distribution.
set -eu
cd "$(dirname "$0")/../.."

PY_URL=https://github.com/niess/python-appimage/releases/download/python3.12/python3.12.15-cp312-cp312-manylinux2014_x86_64.AppImage
PY_SHA256=a6a9bf619a3e21c5623be144d8ac4e458e1a5b5c133b1cc99b142d6e71b82c76
TOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
TOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
PYQT="PyQt6==6.10.2 PyQt6-Qt6==6.10.2"

ver=$(python3 -c 'import re; print(re.search(r"__version__ = \"(.+)\"", open("tytcps/__init__.py").read()).group(1))')
cache=build/appimage-cache
work=build/appimage
app=$work/TYTcps.AppDir
mkdir -p "$cache"

fetch() {    # url sha256 -> path in the cache
    f="$cache/$(basename "$1")"
    if [ ! -s "$f" ]; then
        curl -fL --retry 3 -o "$f.part" "$1" || exit 1
        mv "$f.part" "$f"
    fi
    sum=$(sha256sum "$f" | cut -d' ' -f1)
    if [ -n "$2" ] && [ "$sum" != "$2" ]; then
        echo "checksum mismatch for $f: $sum" >&2; exit 1
    fi
    echo "$(basename "$f") sha256 $sum" >&2
    chmod +x "$f"
    echo "$f"
}

py=$(fetch "$PY_URL" "$PY_SHA256")
tool=$(fetch "$TOOL_URL" "$TOOL_SHA256")

make engine
rm -rf "$work"
mkdir -p "$work"
(cd "$work" && "../../$py" --appimage-extract >/dev/null && mv squashfs-root TYTcps.AppDir)

pybin=$(ls "$app"/opt/python3.*/bin/python3.* | grep -E 'python3\.[0-9]+$' | head -1)
"$pybin" -s -m pip install --no-cache-dir --no-warn-script-location $PYQT

# Keep only the parts of Qt that TYTcps uses: widgets on X11 or Wayland,
# the desktop's look (GTK theme, portal dialogs), SVG for the icon. The rest
# (QML, 3D, multimedia, SQL drivers...) is most of the wheel and would pull
# in system libraries nobody needs.
qt="$app/opt/python3.12/lib/python3.12/site-packages/PyQt6"
keep_py="QtCore QtGui QtWidgets QtDBus QtSvg"
for f in "$qt"/Qt*.abi3.so "$qt"/Qt*.pyi; do
    m=$(basename "$f" | cut -d. -f1)
    case " $keep_py " in *" $m "*) ;; *) rm -f "$f" ;; esac
done
rm -rf "$qt"/bindings "$qt"/lupdate "$qt"/uic "$qt"/Qt6/qml "$qt"/Qt6/translations
keep_lib="Core Gui Widgets DBus Svg XcbQpa WaylandClient WlShellIntegration OpenGL Network"
for f in "$qt"/Qt6/lib/*.so*; do
    b=$(basename "$f")
    case "$b" in
        libicu*|libxcb-cursor*) continue ;;
        libQt6*) m=$(echo "$b" | sed -E 's/^libQt6([A-Za-z]+)\.so.*/\1/')
                 case " $keep_lib " in *" $m "*) continue ;; esac ;;
    esac
    rm -f "$f"
done
for d in "$qt"/Qt6/plugins/*; do
    case $(basename "$d") in
        platforms|platformthemes|platforminputcontexts|imageformats|iconengines|\
        xcbglintegrations|wayland-decoration-client|wayland-graphics-integration-client|\
        wayland-shell-integration) ;;
        *) rm -rf "$d" ;;
    esac
done
rm -f "$qt"/Qt6/plugins/imageformats/libqpdf.so      # needs Qt PDF, which is gone
rm -f "$qt"/Qt6/plugins/imageformats/libqtiff.so     # libtiff5 vs libtiff6 between releases
for f in "$qt"/Qt6/plugins/platforms/*.so; do
    case $(basename "$f") in libqxcb.so|libqwayland*.so|libqoffscreen.so|libqminimal.so) ;; *) rm -f "$f" ;; esac
done

# Qt's X11 plugin needs libxcb-cursor, which many desktops don't install.
# Carry it, from this system or from the distribution's package.
curs=/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0
if [ ! -e "$curs" ]; then
    (cd "$cache" && rm -rf xcb-cursor && apt-get download libxcb-cursor0 >/dev/null &&
        dpkg-deb -x libxcb-cursor0_*.deb xcb-cursor)
    curs=$(ls "$cache"/xcb-cursor/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0)
fi
cp -L "$curs" "$qt/Qt6/lib/libxcb-cursor.so.0"

mkdir -p "$app/usr/share/tytcps"
cp -r tytcps "$app/usr/share/tytcps/"
find "$app/usr/share/tytcps" -name __pycache__ -prune -exec rm -rf {} +

rm -f "$app"/*.desktop "$app"/*.png "$app"/*.svg "$app"/.DirIcon "$app"/AppRun
cp packaging/tytcps.desktop "$app/tytcps.desktop"
cp tytcps/data/tytcps.svg "$app/tytcps.svg"
ln -s tytcps.svg "$app/.DirIcon"
cat > "$app/AppRun" <<'RUN'
#!/bin/sh
here=$(dirname "$(readlink -f "$0")")
export PYTHONPATH="$here/usr/share/tytcps"
export PYTHONNOUSERSITE=1
exec "$here"/opt/python3.12/bin/python3.12 -s -m tytcps "$@"
RUN
chmod 755 "$app/AppRun"

# Everything left must load on this machine: a library that's missing here
# would be missing for users too (make release builds on Ubuntu 22.04 with
# the libraries a desktop has).
missing=$({ find "$qt" -name '*.so*' -type f; echo "$app/usr/share/tytcps/tytcps/libexec/dmrconfig-tyt"; } |
    while read -r f; do
    ldd "$f" 2>/dev/null | awk -v f="$f" '/not found/ { print f ": " $1 }'; done)
if [ -n "$missing" ]; then
    echo "libraries not found:" >&2; echo "$missing" >&2; exit 1
fi

ARCH=x86_64 "$tool" --appimage-extract-and-run "$app" "build/TYTcps-$ver-x86_64.AppImage"
ls -l "build/TYTcps-$ver-x86_64.AppImage"
