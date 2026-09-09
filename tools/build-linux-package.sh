#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir=${1:-"$project_root/dist"}
version=$(sed -n '1p' "$project_root/VERSION")
debian_version=$(printf '%s' "$version" | sed 's/-rc\./~rc./')
package_revision=${ATARI_PACKAGE_REVISION:-}
package_target=${ATARI_PACKAGE_TARGET:-Current Debian-compatible system}

if [ -n "$package_revision" ] && ! printf '%s\n' "$package_revision" \
    | grep -Eq '^-[0-9]+~[a-z0-9][a-z0-9.+]*$'; then
    echo "ATARI_PACKAGE_REVISION must be empty or a Debian revision such as -1~deb13." >&2
    exit 2
fi
if ! printf '%s\n' "$package_target" \
    | grep -Eq '^[A-Za-z0-9][A-Za-z0-9 .()+/-]*$'; then
    echo "ATARI_PACKAGE_TARGET contains unsupported control characters." >&2
    exit 2
fi

package_version=$debian_version$package_revision
architecture=$(dpkg --print-architecture)
package_name=atari-file-forge_${package_version}_${architecture}.deb
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$project_root" log -1 --format=%ct)}
export SOURCE_DATE_EPOCH
build_root=$(mktemp -d)
stage="$build_root/package"
application="$stage/opt/atari-file-forge"

cleanup() {
    rm -rf -- "$build_root"
}
trap cleanup EXIT HUP INT TERM

for command in dpkg-deb python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "$command is required to build the Debian package." >&2
        exit 2
    fi
done

mkdir -p \
    "$application" \
    "$stage/DEBIAN" \
    "$stage/usr/bin" \
    "$stage/usr/share/applications" \
    "$stage/usr/share/doc/atari-file-forge" \
    "$stage/usr/share/icons/hicolor/scalable/apps" \
    "$stage/usr/share/man/man1" \
    "$stage/usr/share/metainfo" \
    "$stage/usr/share/mime/packages" \
    "$stage/usr/share/pixmaps"

cp -a \
    "$project_root/atarinut" \
    "$project_root/atari_floppy" \
    "$project_root/atari_greaseweazle" \
    "$project_root/app" \
    "$project_root/desktop" \
    "$application/"
mkdir -p "$application/tools"
cp "$project_root/tools/linux-desktop-environment.sh" "$application/tools/"
cp "$project_root/VERSION" "$application/"

if [ -n "${ATARI_HXC_RUNTIME_DIR:-}" ]; then
    for required in \
        bin/hxcfe \
        lib/libhxcfe.so \
        lib/libusbhxcfe.so \
        share/licenses/HxCFloppyEmulator-COPYING; do
        if [ ! -f "$ATARI_HXC_RUNTIME_DIR/$required" ]; then
            echo "ATARI_HXC_RUNTIME_DIR is missing $required." >&2
            exit 2
        fi
    done
    cp -a "$ATARI_HXC_RUNTIME_DIR/." "$application/native/"
else
    "$project_root/tools/build-hxc-runtime.sh" "$application/native"
fi

python3 -m pip install \
    --disable-pip-version-check \
    --no-compile \
    --target "$application/vendor" \
    -r "$project_root/packaging/linux/requirements-debian.txt"

cp "$project_root/packaging/linux/atari-file-forge" "$stage/usr/bin/"
sed \
    -e 's|@EXEC@|/usr/bin/atari-file-forge|g' \
    -e 's|@TRY_EXEC@|/usr/bin/atari-file-forge|g' \
    "$project_root/packaging/linux/uk.co.atarifileforge.AtariFileForge.desktop.in" \
    > "$stage/usr/share/applications/uk.co.atarifileforge.AtariFileForge.desktop"
cp "$project_root/app/static/favicon.svg" \
    "$stage/usr/share/icons/hicolor/scalable/apps/atari-file-forge.svg"
cp -a "$project_root/packaging/linux/icons/." \
    "$stage/usr/share/icons/hicolor/"
cp "$project_root/packaging/linux/icons/256x256/apps/atari-file-forge.png" \
    "$stage/usr/share/pixmaps/atari-file-forge.png"
cp "$project_root/packaging/linux/uk.co.atarifileforge.AtariFileForge.xml" \
    "$stage/usr/share/mime/packages/"
cp "$project_root/packaging/linux/uk.co.atarifileforge.AtariFileForge.metainfo.xml" \
    "$stage/usr/share/metainfo/"
gzip -n -9 -c "$project_root/packaging/linux/atari-file-forge.1" \
    > "$stage/usr/share/man/man1/atari-file-forge.1.gz"

cp \
    "$project_root/README.md" \
    "$project_root/THIRD_PARTY_NOTICES.md" \
    "$stage/usr/share/doc/atari-file-forge/"
cp "$project_root/LICENSE" "$stage/usr/share/doc/atari-file-forge/copyright"
cp -a "$project_root/docs" "$stage/usr/share/doc/atari-file-forge/handbook"

# Bytecode compiled by the build machine's interpreter is wrong for any other
# Python the package supports, and would be preferred over the source it no
# longer matches. Ship only source; the interpreter caches what it needs.
find "$stage" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$stage" -type f -name '*.py[co]' -delete

installed_size=$(du -sk "$stage" | awk '{print $1}')
cat > "$stage/DEBIAN/control" <<EOF
Package: atari-file-forge
Version: $package_version
Section: utils
Priority: optional
Architecture: $architecture
Installed-Size: $installed_size
Maintainer: Atari File Forge contributors <peteclarke-del@users.noreply.github.com>
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-webkit-6.0, shared-mime-info, desktop-file-utils
Homepage: https://github.com/peteclarke-del/AtariFileForge
X-Atari-Target: $package_target
Description: Atari media image workshop
 Browse, edit, validate and convert Atari, Atari 600, Atari 4000 and
 TOS disk, dms, ROM and hard-drive images from a native GTK application.
EOF
cp "$project_root/packaging/linux/postinst" "$stage/DEBIAN/postinst"
cp "$project_root/packaging/linux/postrm" "$stage/DEBIAN/postrm"

find "$stage" -type d -exec chmod 755 {} +
find "$stage" -type f -exec chmod 644 {} +
if [ -d "$application/vendor/bin" ]; then
    find "$application/vendor/bin" -type f -exec chmod 755 {} +
fi
find "$application/native/bin" -type f -exec chmod 755 {} +
chmod 755 \
    "$stage/DEBIAN/postinst" \
    "$stage/DEBIAN/postrm" \
    "$stage/usr/bin/atari-file-forge"
find "$stage" -exec touch -d "@$SOURCE_DATE_EPOCH" {} +

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate \
        "$stage/usr/share/applications/uk.co.atarifileforge.AtariFileForge.desktop"
fi
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate --no-net \
        "$stage/usr/share/metainfo/uk.co.atarifileforge.AtariFileForge.metainfo.xml"
fi

mkdir -p "$output_dir"
dpkg-deb --build --root-owner-group "$stage" "$output_dir/$package_name"
echo "$output_dir/$package_name"
