// Builds never publish directly: the guarded release workflow uploads artifacts.
module.exports = {
  appId: 'net.lecluse.galaris',
  productName: 'Galaris',
  directories: { output: 'release' },
  files: ['dist/**/*', '!dist/THIRD-PARTY-NOTICES.txt', 'dist-main/**/*', 'package.json'],
  extraResources: [
    { from: '../front/public/pwa/icon-512.png', to: 'icon.png' },
    { from: '../LICENSE.md', to: 'LICENSE-Galaris.md' },
    { from: 'dist/THIRD-PARTY-NOTICES.txt', to: 'THIRD-PARTY-NOTICES.txt' }
  ],
  asar: true,
  forceCodeSigning: process.env.DESKTOP_REQUIRE_SIGNING === '1',
  artifactName: 'Galaris-${version}-${arch}.${ext}',
  publish: [{ provider: 'github', owner: 'lecluse-net', repo: 'galaris', vPrefixedTagName: false, releaseType: 'release' }],
  win: { target: ['nsis'], icon: '../front/public/pwa/icon-512.png' },
  nsis: { oneClick: false, perMachine: false, allowToChangeInstallationDirectory: true, deleteAppDataOnUninstall: false },
  linux: {
    target: ['AppImage', 'deb'],
    category: 'Office',
    maintainer: 'Galaris contributors (https://github.com/lecluse-net/galaris/issues)',
    executableName: 'galaris-desktop',
    syncDesktopName: true,
    icon: '../front/public/pwa/icon-512.png',
    desktop: { entry: { StartupWMClass: 'galaris-desktop' } }
  }
}
