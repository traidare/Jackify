{
  outputs = inputs:
    inputs.flake-parts.lib.mkFlake {inherit inputs;} ({...}: {
      systems = ["x86_64-linux" "aarch64-linux"];

      perSystem = {
        config,
        system,
        ...
      }: let
        pkgs = import inputs.nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg:
            builtins.elem (inputs.nixpkgs.lib.getName pkg) [
              "steam"
              "steam-run"
              "steam-unwrapped"
            ];
        };

        jackify-engine = inputs.jackify-engine.packages.${system}.default;
      in {
        packages = {
          jackify = pkgs.python3Packages.callPackage ./nix/package.nix {
            inherit jackify-engine;
          };
          default = config.packages.jackify;
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            (python3.withPackages (python-pkgs:
              with python-pkgs; [
                packaging
                psutil
                pycryptodome
                pyside6
                pyyaml
                requests
                tqdm
                vdf
                watchdog
              ]))
            # Runtime tools
            _7zip-zstd
            cabextract
            gnutar
            libnotify
            unzip
            winetricks
            xdg-utils
          ];

          shellHook = ''
            export JACKIFY_ENGINE_PATH="${jackify-engine}/bin/jackify-engine"
          '';
        };

        _module.args.pkgs = pkgs;
      };
    });

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    jackify-engine = {
      url = "github:traidare/dev-jackify-engine";
      inputs = {
        flake-parts.follows = "flake-parts";
        nixpkgs.follows = "nixpkgs";
      };
    };
  };
}
