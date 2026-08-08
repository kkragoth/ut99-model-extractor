# UT99 (v436) LODMesh extractor

Standalone Python tool that decodes the Unreal Engine 1 (UT99 v436) `.u` package
format and extracts player `LodMesh`/`Mesh` exports: per-frame vertices, faces,
wedges, animation sequences, materials, and the import transform. Any animation
frame can be exported to Wavefront OBJ for visual verification.

Requires Python 3.8+, **no third-party dependencies** (stdlib only).

## Usage

    # List mesh-like exports in a package
    python extract_mesh.py Botpack.u

    # Parse one mesh and print its summary (defaults to the first mesh found)
    python extract_mesh.py Botpack.u 3251

    # Export an animation frame to OBJ (frame defaults to 0)
    python extract_mesh.py Botpack.u 3251 --obj 25 commando_breath.obj

    # Dump every serialized field + file offset of a mesh blob (debug)
    python mesh_blob.py Botpack.u 3251

## What it decodes

- Full UE1 package header and name/import/export tables, including v436
  `FCompactIndex` variable-length integers.
- The complete v436 `ULodMesh` serialized layout - see `format.md` for the
  field order and every gotcha (RotOrigin is 3x INT32, FBox is 25 bytes,
  FMeshVert is a packed 11/11/10-bit int, wedge `iVertex` excludes
  `SpecialVerts`, ...).
- World-space mesh transform: `(vert - Origin)` rotated by `RotOrigin`, then
  scaled by `MeshScale` (rotate-then-scale, matching UT's FCoords math).

## Validation

`parse_mesh_blob` returns a `leftover == 0` check (every byte of the export
blob consumed). Internal consistency anchors - `Verts == FrameVerts*FrameCount`,
`ModelVerts == CollapsePointThus`, `Wedges == CollapseWedgeThus`,
`Materials == Textures`, all face/wedge indices in range - hold for the retail
Commando mesh.

## File layout

    extract_mesh.py   decoder + CLI (UTPackage, parse_mesh_blob, parse_lod_mesh,
                      mesh_to_world, export_obj)
    mesh_blob.py      debug field/offset dumper
    format.md         the proven v436 ULodMesh on-disk layout

## References

- gildor2/UEViewer `Unreal/UnrealMesh/UnMesh1.cpp` (`SerializeLodMesh1`) - UE1
  layout + wedge SpecialVerts remap.
- study-game-engines/surreal `SurrealEngine/UObject/UMesh.cpp` - v436
  `UMesh::Load` / `ULodMesh::Load` (source of the RotOrigin 3xINT32 fix).
- UT99 engine headers: `Core/Inc/UnTemplate.h` (TLazyArray),
  `Engine/Inc/UnMesh.h` (FMeshVert/Tri/Face/Wedge/Material),
  `Engine/Inc/UnAnim.h` (FMeshAnimSeq).
