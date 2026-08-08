# UT99 (v436) ULodMesh / UMesh serialized data format

Verified against the retail `System\Botpack.u` (package tag `0x9E2A83C1`,
file version 69 / v436), export 3251 (`Commando`, class import -49 = `LodMesh`,
serial 969846 bytes @ file offset 4812534). The parser is `extract_mesh.py`
(`parse_mesh_blob`) with the standalone debug dump `mesh_blob.py`; both consume
the field order below and validate with `leftover == 0`.

## Field order (in stream order)

    FName      objName                 compact index            (e.g. 7454 = 'None')
    FBox       boundingBox             25 B: Min(3f) Max(3f) IsValid(1 B)
    FSphere    boundingSphere          16 B
    TLazyArray<FMeshVert>      Verts
    TLazyArray<FMeshTri>       Tris
    TArray<FMeshAnimSeq>       AnimSeqs
    TLazyArray<FMeshVertConnect> Connects
    FBox       boundingBox2            UPrimitive fields re-serialized
    FSphere    boundingSphere2
    TLazyArray<int>            VertLinks
    TArray<UTexture*>          Textures        (array of FName compacts)
    TArray<FBox>               BoundingBoxes   (25 B each)
    TArray<FSphere>            BoundingSpheres (16 B each)
    INT        VertexCount     (= FrameVerts)
    INT        FrameCount      (= AnimFrames)
    UINT       AndFlags, OrFlags
    FVector    MeshScale
    FVector    MeshOrigin
    FRotator   RotOrigin       3 x INT32  (NOT 3 x _WORD!)
    INT        CurPoly, CurVertex
    TArray<float> TextureLOD                (ver >= 66)
    [ULodMesh:]
    TArray<_WORD> CollapsePointThus
    TArray<_WORD> FaceLevel
    TArray<FMeshFace> Faces                 (8 B: 3x _WORD iWedge + _WORD MaterialIndex)
    TArray<_WORD> CollapseWedgeThus
    TArray<FMeshWedge> Wedges               (4 B: _WORD iVertex + _WORD UV)
    TArray<FMeshMaterial> Materials         (8 B: DWORD PolyFlags + INT TextureIndex)
    TArray<FMeshFace> SpecialFaces          (8 B)
    INT        ModelVerts, SpecialVerts
    FLOAT      MeshScaleMax
    FLOAT      LODHysteresis, LODStrength
    INT        LODMinVerts
    FLOAT      LODMorph, LODZDisplace
    TArray<_WORD> RemapAnimVerts
    INT        OldFrameVerts

The `UMesh`-vs-`ULodMesh` split is handled by the class name: plain `Mesh`
class exports skip the `[ULodMesh:]` tail (umodel converts `Tris`->`Faces`/
`Wedges` in memory; no tail on disk). Everything below the `[ULodMesh:]`
marker is what this decode targets.

## Encoding details / gotchas

- **FCompactIndex** (all counts, FName/object refs, AnimSeq Name/Group,
  AnimNotify Function): `b0 = read(); val = b0&0x3F; shift = 6;
  while b0&0x40: b = read(); val |= (b&0x7F)<<shift; shift += 7`
  then negate if `b0&0x80`. The umodel-style `(b>>2)|(b&1)<<6` variant is
  wrong for this file.
- **TLazyArray** on disk = `[INT skipPos][compact count][count elements inline]`.
  `skipPos` = absolute file offset of the END of the inline data (cross-check:
  `inline_ok`). BoundingBoxes/BoundingSpheres also ride in these per-frame.
- **FBox is 25 bytes** in v436 (`Min`+`Max`+`IsValid` byte) - both as the
  standalone `boundingBox` field and inside `BoundingBoxes`.
- **`FRotator RotOrigin` is 3 x INT32 (12 bytes)** in v436, not 3 x _WORD.
  This is the single most damaging gotcha: reading it as 6 bytes shifts the
  entire ULodMesh tail and every count/float after it.
- **FMeshAnimNotify.Function is a compact FName** (variable length), so
  AnimSeqs records have variable size; fixed 8 B/notify misaligns the stream.
- **Textures** are FName compacts (object refs), not fixed 2 B ints.
- **FMeshWedge.iVertex is a MODEL-vert index** that EXCLUDES the special verts;
  add `SpecialVerts` to get the index into each frame's vertex block
  (umodel: `Wedges[i].iVertex += tmpSpecialVerts`). `ModelVerts + SpecialVerts
  == VertexCount`.
- **FMeshVert** = one packed INT32: `X = 11 bits` (sign-extended low 11),
  `Y = 11 bits` (bits 11-21), `Z = 10 bits` (top 10, signed). SurrealEngine
  formula: `x=(pv<<21)>>21; y=(pv<<10)>>21; z=pv>>22`.
- **Vertex layout is frame-major**: `verts[f*VertexCount + v]`; the visible
  model verts of frame `f` are `verts[f*VertexCount + SpecialVerts .. +VertexCount)`.
- **FMeshUV** = 2 bytes (`U`, `V` as bytes 0..255), not two _WORDs.

## Internal consistency anchors (validate your parse against these)

    Verts.count        == VertexCount * FrameCount        (Commando: 332 x 700 = 232400)
    ModelVerts         == CollapsePointThus.count        (329 == 329)
    Faces.count        == FaceLevel.count                (642 == 642)
    Wedges.count       == CollapseWedgeThus.count        (487 == 487)
    Materials.count    == Textures.count                 (4 == 4)
    max(face.iWedge)   < Wedges.count
    max(wedge.iVertex) < ModelVerts
    end_pos            == blob size                      (leftover == 0)

## Commando (export 3251) reference values

    boundingBox    = [-982,-897,-488]..[942,1023,509], IsValid=1
    boundingSphere = center(-20,63,10.5) R=1214.2
    MeshScale      = (0.0625, 0.0625, 0.125)   (UT meshes: 2x vertical res)
    MeshOrigin     = (-150, 40, 0)
    RotOrigin      = (0, 16384, -16384)
    VertexCount=332, FrameCount=700, ModelVerts=329, SpecialVerts=3
    Faces=642, Wedges=487, Materials=4 ([(0,0),(0,1),(0,2),(0,3)]), SpecialFaces=1
    AnimSeqs=69 (All 0+700, GutHit 0+1, AimDnLg 1+1, ..., Breath1 25+7, ...)
    TextureLOD   = 4 x 1.0

## Import transform to actor-local space (pelvis at origin, Z up)

    P = (vert - MeshOrigin) * MeshScale              # scale first
    P = P.TransformPointBy(RotCoords)                # then rotate by RotOrigin

**Scale-then-rotate.** This matches the engine render path: the `GetFrame`
coords chain applies `FScale(Scale)` inside the coords (scale applied first).
The old rotate-then-scale formulation was WRONG for these meshes (their
`RotOrigin = (0,16384,-16384)` maps raw X->world Z, raw Y(up)->world X,
raw Z->world Y, so the mesh stands up along +Z). SurrealEngine's yaw sign is
opposite to `Core\Inc\UnMath.h:1934` (`FCoords::operator*=(FRotator)`:
Yaw->Pitch->Roll, yaw `XAxis=(+cos,+sin,0)`, `YAxis=(-sin,+cos,0)`) - use the
engine's sign, not SurrealEngine's.

## References

- `extract_mesh.py` - `parse_mesh_blob` (decoder), `parse_lod_mesh`
  (MeshData), `export_obj --obj <frame>`.
- `mesh_blob.py` - field/offset dump of a mesh blob.
- gildor2/UEViewer `Unreal\UnrealMesh\UnMesh1.cpp` `SerializeLodMesh1` - UE1
  layout + wedge SpecialVerts remap.
- study-game-engines/surreal `SurrealEngine\UObject\UMesh.cpp` - v436 `UMesh::
  Load` / `ULodMesh::Load` (source of the RotOrigin 3xINT32 fix).
- Engine headers: `Core\Inc\UnTemplate.h` (TLazyArray),
  `Engine\Inc\UnMesh.h` (FMeshVert/Tri/Face/Wedge/Material structs),
  `Engine\Inc\UnAnim.h` (FMeshAnimSeq).
