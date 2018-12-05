with import <nixpkgs> {}; {
  pyEnv = stdenv.mkDerivation {
    name = "octodon";
    buildInputs = [ stdenv python27Full python27Packages.virtualenv hamster-time-tracker libxml2 git subversion ];
    LIBRARY_PATH="${libxml2}/lib";
    shellHook = ''
      unset http_proxy
      export GIT_SSL_CAINFO=/etc/ssl/certs/ca-bundle.crt
      export SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt
      export LIBRARY_PATH=${pkgs.openssl.out}/lib
    '';
  };
}
