with import <nixpkgs> {}; {
  pyEnv = stdenv.mkDerivation {
    name = "octodon";
    buildInputs = [ stdenv python27Full python27Packages.virtualenv hamster-time-tracker libxml2 git subversion ];
    LIBRARY_PATH="${libxml2}/lib";
  };
}
