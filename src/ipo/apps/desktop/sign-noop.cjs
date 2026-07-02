// No-op code-signing hook for electron-builder (Windows).
//
// The app ships UNSIGNED — the operator signs the installer + binaries with their own certificate
// (Claude never holds signing keys). Providing this custom `win.sign` hook stops electron-builder
// from invoking its built-in winCodeSign/signtool toolchain (whose cached archive contains macOS
// symlinks that need Windows Developer Mode to extract). Crucially, the *edit* step still runs, so
// rcedit embeds our branded icon + version metadata into the executable.
//
// To produce a SIGNED build, remove this hook and sign with a real certificate instead.
exports.default = async function sign() {
  // intentionally does nothing
}
