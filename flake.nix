{
  description = "krusta: fast interfaces in place of some sites' own apps (so far X), as a Firefox extension on the browser's sessions";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    fenix.url = "github:nix-community/fenix"; # stable Rust plus the wasm32 target for the client
    fenix.inputs.nixpkgs.follows = "nixpkgs";
    crane.url = "github:ipetkov/crane"; # dependencies built once and cached; only krusta's crates rebuild
  };

  outputs = {
    nixpkgs,
    fenix,
    crane,
    ...
  }: let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    build = profile:
      pkgs.callPackage ./nix/package.nix {
        fenix = fenix.packages.${system};
        craneLib = crane.mkLib pkgs;
        inherit profile;
      };
    krusta = build "release";
    tested = build "fast"; # what the VM suites and their plants run: no LTO, built in parallel (Cargo.toml)
    # What tests/lint.sh runs, besides cargo fmt
    lintTools = [
      pkgs.alejandra
      pkgs.deadnix
      pkgs.taplo
      pkgs.ruff
      pkgs.mypy
      pkgs.prettier
      pkgs.oxlint
      pkgs.shellcheck
      pkgs.zizmor
    ];
  in {
    packages.${system} = {
      inherit (krusta) extension xpi;
      default = krusta.xpi;
    };

    checks.${system} =
      krusta.checks
      # Each interface's VM suite, vm-<id>, from sites/<id>/tests/vm.nix; .plants: every planted bug, six VMs at once.
      // pkgs.lib.mapAttrs' (id: _: {
        name = "vm-${id}";
        value = import ./sites/${id}/tests/vm.nix {
          inherit pkgs;
          krusta = tested;
        };
      })
      krusta.sites;

    devShells.${system} = {
      default = pkgs.mkShell {
        packages = [krusta.toolchain pkgs.wasm-bindgen-cli pkgs.binaryen] ++ lintTools;
      };
      # tests/lint.sh alone, for CI (.github/workflows/quality.yml): no compiler or wasm target to fetch
      lint = pkgs.mkShellNoCC {packages = [krusta.fmtToolchain] ++ lintTools;};
    };

    formatter.${system} = pkgs.alejandra;
  };
}
