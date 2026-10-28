# Each site's WebAssembly client inside the unpacked extension, the .xpi Zen installs, and the clippy checks.
# crane builds the dependencies once per target into their own derivations, so a source change recompiles only
# krusta's own crates.
{
  binaryen,
  craneLib,
  fenix,
  lib,
  runCommand,
  wasm-bindgen-cli,
  zip,
  profile ? "release", # `release` ships; the suites test `fast` (Cargo.toml), the same optimisation built in parallel
}: let
  toolchain = fenix.combine [
    fenix.stable.rustc
    fenix.stable.cargo
    fenix.stable.clippy
    fenix.latest.rustfmt # nightly, for rustfmt.toml's unstable options; the compiler stays stable
    fenix.stable.rust-std
    fenix.targets.wasm32-unknown-unknown.stable.rust-std # the clients
  ];
  # The same cargo and rustfmt without the compiler, for `cargo fmt` in the lint shell (tests/lint.sh).
  fmtToolchain = fenix.combine [fenix.stable.cargo fenix.latest.rustfmt];
  crane = craneLib.overrideToolchain (_: toolchain);

  # Every folder in sites/ is an interface, named after it (docs/design.md, Sites): its site.json, with that name
  # added as id, beside an API crate <id>-api in api/ and a client crate <id>-web in web/.
  sites = lib.mapAttrs (id: _: lib.importJSON (../sites + "/${id}/site.json") // {inherit id;}) (
    lib.filterAttrs (_: type: type == "directory") (builtins.readDir ../sites)
  );
  ids = lib.attrNames sites;
  crates = suffix: lib.concatMapStringsSep " " (id: "-p ${id}${suffix}") ids;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions (
      [../Cargo.toml ../Cargo.lock]
      ++ lib.concatMap (id: [(../sites + "/${id}/api") (../sites + "/${id}/web")]) ids
    );
  };

  common = {
    inherit src;
    pname = "krusta";
    version = "0.1.0";
    strictDeps = true;
    doCheck = false; # no unit tests (.claude/rules/002-dev.md, Tests)
    CARGO_PROFILE = profile;
  };
  webArgs =
    common
    // {
      cargoExtraArgs = crates "-web";
      CARGO_BUILD_TARGET = "wasm32-unknown-unknown";
    };
  webDeps = crane.buildDepsOnly webArgs;
  nativeDeps = crane.buildDepsOnly (common // {cargoExtraArgs = crates "-api";});

  # Each site's client as client.js and client_bg.wasm, which content.js loads on that site only.
  clients = lib.mapAttrs (id: _:
    crane.buildPackage (webArgs
      // {
        pname = "${id}-web";
        cargoExtraArgs = "-p ${id}-web";
        cargoArtifacts = webDeps;
        nativeBuildInputs = [wasm-bindgen-cli binaryen];
        installPhaseCommand = ''
          mkdir -p $out
          wasm-bindgen --target web --no-typescript --out-name client --out-dir $out \
            target/wasm32-unknown-unknown/${profile}/${lib.replaceStrings ["-"] ["_"] id}_web.wasm
          wasm-opt -Oz --enable-bulk-memory --enable-nontrapping-float-to-int -o $out/client_bg.wasm $out/client_bg.wasm
        '';
      }))
  sites;

  matches = site: map (host: "https://${host}/*") site.hosts;
  # The sites' parts of the manifest, from site.json, so a new site needs no edit to it.
  manifest =
    lib.importJSON ../extension/manifest.json
    // {
      # Each site's hosts, and its own app's script addresses, which background.js blocks.
      host_permissions = lib.concatMap (site: matches site ++ map (prefix: "${prefix}*") site.appScripts) (lib.attrValues sites);
      web_accessible_resources =
        lib.mapAttrsToList (id: site: {
          resources = map (file: "sites/${id}/${file}") ["client.js" "client_bg.wasm" "style.css"];
          matches = matches site;
        })
        sites;
    };

  # The unpacked add-on: about:debugging loads its manifest.json; the .xpi is the same files zipped. sites.js gives
  # background.js and content.js every site.json as SITES.
  extension = runCommand "krusta-extension" {} ''
    cp -r ${../extension} $out
    chmod -R u+w $out
    cp ${builtins.toFile "manifest.json" (builtins.toJSON manifest)} $out/manifest.json
    cp ${builtins.toFile "sites.js" "const SITES = ${builtins.toJSON (lib.attrValues sites)}\n"} $out/sites.js
    ${lib.concatMapStrings (id: ''
        mkdir -p $out/sites/${id}
        cp ${clients.${id}}/client.js ${clients.${id}}/client_bg.wasm $out/sites/${id}/
        cp ${../sites + "/${id}/style.css"} $out/sites/${id}/style.css
      '')
      ids}
  '';
  xpi = runCommand "krusta.xpi" {nativeBuildInputs = [zip];} "cd ${extension} && zip -qrX $out .";

  checks = {
    clippy-api = crane.cargoClippy (common
      // {
        cargoArtifacts = nativeDeps;
        cargoClippyExtraArgs = "${crates "-api"} -- -D warnings";
      });
    clippy-web = crane.cargoClippy (webArgs
      // {
        cargoArtifacts = webDeps;
        cargoClippyExtraArgs = "${crates "-web"} -- -D warnings";
      });
  };
in {
  inherit toolchain fmtToolchain sites clients extension xpi checks;
}
