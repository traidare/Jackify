{
  buildPythonApplication,
  lib,
  python,
  # Build dependencies
  setuptools,
  wheel,
  # Runtime Python dependencies
  cryptography,
  packaging,
  psutil,
  pycryptodome,
  pyside6,
  pyyaml,
  requests,
  tqdm,
  vdf,
  watchdog,
  # Desktop file integration
  copyDesktopItems,
  makeDesktopItem,
  # Qt wrapping
  makeWrapper,
  qt6,
  # Runtime tools
  _7zip-zstd,
  cabextract,
  gnutar,
  jackify-engine,
  libnotify,
  unzip,
  winetricks,
  xdg-utils,
  zlib,
}: let
  src = lib.cleanSource ../.;
  version = let
    initFile = builtins.readFile ../jackify/__init__.py;
    versionLine = lib.findFirst (lib.hasPrefix "__version__") null (lib.splitString "\n" initFile);
    versionMatch = builtins.match ''__version__ = "([^"]+)"'' versionLine;
  in
    if versionMatch == null
    then throw "Could not parse Jackify version from jackify/__init__.py"
    else builtins.elemAt versionMatch 0;
in
  buildPythonApplication {
    pname = "jackify";
    inherit version src;
    pyproject = true;

    build-system = [
      setuptools
      wheel
    ];

    nativeBuildInputs = [
      copyDesktopItems
      makeWrapper
      qt6.wrapQtAppsHook
    ];

    buildInputs = [
      qt6.qtwayland
      zlib
    ];

    patches = [
      ./patches/fix-protocol-registration.patch
      ./patches/add-pyproject.patch
      ./patches/disable-auto-update.patch
      ./patches/fix-protocol-handler.patch
      ./patches/fix-settings-oauth-freeze.patch
      ./patches/use-steam-run.patch
    ];

    dependencies = [
      cryptography
      packaging
      psutil
      pycryptodome
      pyside6
      pyyaml
      requests
      tqdm
      vdf
      watchdog
    ];

    doCheck = false;

    # Prevent double-wrapping: wrapQtAppsHook wraps via wrapQtApp in postFixup
    dontWrapQtApps = true;

    # Remove bundled tool binaries — provided via PATH by postFixup
    postInstall = ''
      for bin in winetricks cabextract 7z 7zz; do
        rm -f "$out/${python.sitePackages}/jackify/tools/$bin"
      done
    '';

    postFixup = ''
      wrapQtApp "$out/bin/jackify" \
        --set JACKIFY_ENGINE_PATH "${jackify-engine}/bin/jackify-engine" \
        --prefix LD_LIBRARY_PATH : ${lib.makeLibraryPath [zlib]} \
        --prefix PATH : ${lib.makeBinPath [
        xdg-utils
        libnotify
        winetricks
        cabextract
        _7zip-zstd
        gnutar
        unzip
      ]}
    '';

    desktopItems = [
      (makeDesktopItem {
        name = "jackify";
        exec = "jackify %u";
        desktopName = "Jackify";
        comment = "Wabbajack modlist installation and configuration tool for Linux";
        mimeTypes = ["x-scheme-handler/jackify"];
        categories = [
          "Game"
          "Utility"
        ];
        terminal = false;
      })
    ];

    passthru = {
      inherit jackify-engine;
    };

    meta = {
      description = "Wabbajack modlist installation and configuration tool for Linux";
      homepage = "https://codeberg.org/traidare/Jackify";
      license = lib.licenses.gpl3Only;
      platforms = lib.platforms.linux;
      mainProgram = "jackify";
    };
  }
