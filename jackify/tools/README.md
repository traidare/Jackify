# Jackify Tools Directory

This directory contains utility tools bundled with Jackify for self-contained AppImage distribution.

## How It Works

**In Git Repository**: This directory only contains this README and .gitignore (no binaries).

**During Build**: The `build_appimage_simple.sh` script downloads required tools from their official sources.

**In AppImage**: Tools are bundled for self-contained distribution (users don't need to install dependencies).

## Tools Downloaded During Build

### winetricks
- **Source**: https://github.com/Winetricks/winetricks
- **License**: LGPL v2.1
- **Purpose**: Wine prefix configuration and Windows component installation
- **Downloaded from**: GitHub master branch (latest version)

### cabextract
- **Source**: https://github.com/kyz/cabextract
- **License**: GPL v3
- **Purpose**: Microsoft Cabinet file extraction
- **Downloaded from**: GitHub releases (v1.11)

### 7-Zip (7z / 7zz)
- **Source**: https://www.7-zip.org/
- **License**: GNU LGPL + unRAR restriction
- **Purpose**: Archive extraction and compression
- **Downloaded from**: Official 7-Zip website

### lz4
- **Source**: System package (copied from /usr/bin/lz4)
- **License**: BSD 2-Clause
- **Purpose**: Fast compression for TTW installer patch decompression
- **Note**: Copied from build system, not downloaded

## Why Not Store in Git?

1. **Repository Size**: Binaries total ~11MB, bloating git history
2. **Updates**: Tools update independently of Jackify code
3. **Professional Practice**: Industry standard separates source code from build artifacts
4. **Licensing**: Clear separation between our code and third-party binaries

## For Developers

When building locally with `./build_appimage_simple.sh`, these tools are automatically downloaded.

If build fails to download tools, the script will attempt to use system versions as fallback.

See `THIRD_PARTY_NOTICES.md` in project root for complete licensing information.
