<p align="right"><a href="../../fr/components/resource-previews.md">Français</a> · <strong>English</strong></p>

# 3D resource previews

Discussion attachments, resources referenced in messages and document attachments
share one 3D viewer. Thumbnails open an interactive view with orbit, zoom, pan,
reset and fullscreen controls. The original file remains downloadable. Escape,
the close button or a click on the backdrop closes the view.

Shortcuts apply while the scene has focus, on opening, after clicking the scene or
after selecting it with Tab. The help button lists the controls.

| Action | Mouse | Keyboard |
|---|---|---|
| Orbit the object | Left button + drag | Arrow keys |
| Pan the view | Right button + drag | Shift + arrow keys |
| Zoom | Wheel or middle button + drag | + / − |
| Reset | Reset button | Home |
| Close | Close button or backdrop | Escape |

On touchscreens, one finger orbits the object; two fingers pan or pinch to zoom.
Keyboard and toolbar zoom respect the same distance limits as the mouse. Browser
shortcuts using Ctrl, Alt or Cmd remain available.

| Format | Display |
|---|---|
| GLB | Embedded geometry and materials, glTF 2.0 |
| glTF | Data and textures embedded in the file |
| OBJ | Geometry and vertex colors; neutral material without external MTL or textures |
| STL | Geometry, ASCII or binary files |
| PLY | Meshes or point clouds, vertex colors when present |

STEP, IFC, FBX and native authoring formats are not interpreted by this viewer.
GLB/glTF resources depending on separate files must be exported with embedded
dependencies. Draco compression and KTX2 textures are not supported; Meshopt
compression is supported. The view is static: animations are not played. Dimensions
are not manufacturing measurements.

## Thumbnails and loading

PNG thumbnails are generated in the browser when an attachment approaches the
viewport. Generation is sequential to limit simultaneous graphics contexts.
After capture, geometry, materials, textures and the WebGL context are released;
only the thumbnail remains in memory while the attachment is displayed. There is
no server thumbnail cache: thumbnails are regenerated after a page reload.

Three.js is imported on demand. Interactive views render on opening, resizing and
interaction, without a permanent render loop. Preview limits are 32 MiB per file
and 2 million vertices. Downloads remain available after failure, and the viewer
offers a retry action.

## Integration

`front/core/util` exposes `Model3dSource`, `model3dFormat`, `Model3dThumbnail` and
`Model3dViewer`. Each domain supplies a name, MIME type, size when known, a key
including the authorization scope, and a reader using its authorized API. The
viewer does not know business domains or their identifiers. Loads finishing after
closure or a resource change are ignored and cleaned up.

`FullscreenPreview` accepts `spatial` to hide its 2D zoom controls: the 3D camera
then owns zoom and reset. glTF documents are checked before loading; no external
or relative URL from a model is downloaded.

Unit tests live in `front/core/util/model3d.test.mjs`. The Chromium scenarios in
`front/browser-tests/model3d.spec.mjs` mount all three real components with mocked APIs
and check thumbnail pixels, interactions and cleanup. They are collected by
`make tests-front-components` and CI in an isolated environment without application
data. See [the testing layers](../dev/testing.md).
