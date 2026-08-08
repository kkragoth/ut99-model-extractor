# UT99 player-mesh extractor: findings & how-to

Status: **working**. `extract_mesh.py` correctly extracts a player LODMesh
from Botpack.u and exports Blender-ready OBJ frames. Read this before using or
modifying the extractor.

## Environment gotcha (Python)

- On the dev machine the chocolatey `python` shim is broken
  (`STATUS_DLL_NOT_FOUND`). Use the Windows Store interpreter: **`python3`**.

## The one big bug that was fixed: rotation math

`ut_rotation_matrix` (and the mesh import transform) was originally ported from
SurrealEngine, whose **yaw sign is opposite** to the real UT99 engine. This made
exported meshes lie on their side. The fix:

- Authoritative source is the real engine, `Core\Inc\UnMath.h:1934`
  (`FCoords::operator*=(FRotator)`): composes **Yaw -> Pitch -> Roll** onto
  UnitCoords, with yaw `XAxis=(+cosY, +sinY, 0)`, `YAxis=(-sinY, +cosY, 0)`.
- `mesh_to_world` does **scale-then-rotate**:
  `p = (vert - Origin) * Scale` then `p.TransformPointBy(RotCoords)`. This
  matches the engine render path (the `GetFrame` coords chain applies `FScale`
  inside the coords = scale applied first).
- The native ragdoll capture code does **rotate-then-scale**, but since
  `MeshScale.X == MeshScale.Y` for these meshes the horizontal orientation is
  identical; only vertical differs, and `FitScale` absorbs it. Do not "fix" the
  order without re-checking the game.

## Import transform / orientation cheat-sheet

    P = (vert - MeshOrigin) * MeshScale            # scale first
    world = P.TransformPointBy(ut_rotation_matrix(RotOrigin))

For Commando/SelectionMale1 (`RotOrigin = (0, 16384, -16384)`):

    raw X -> world +Z      raw Y (up) -> world +X      raw Z -> world +Y

Net result: mesh stands **up along world Z** (head +Z, feet -Z), the same frame
as the ragdoll skeleton boxes. Verified: Commando Look f96 bbox
`Z[-40.0..44.3]`, skeleton boxes `Z[-39.5..38.0]`.

## FitScale (matches the corpse exactly)

The native ragdoll scales the captured pose by

    FitScale = SkeletonBodyLen / LongAxis

- `SkeletonBodyLen = 77.5` = `(Head.CZ + Head.HZ) - (FootL.CZ - FootL.HZ)`
  (from `GRagdollBoneDefs` in `RagdollCarcass.cpp`).
- For Commando Look f96: `LongAxis = 81.938`, so `FitScale = 0.9458`. Applying
  it gives height exactly 77.5, matching the skeleton.
- Export with `--fit 0.9458` to get the exact in-game proportions.

## Player-select viewer mesh: use the Selection* meshes, NOT Commando

The in-game player-select screen does **not** show the `Commando` animation
mesh. It uses dedicated low-poly viewer meshes with arms straight down, no
weapon, and a breathing idle:

    [10409] SelectionFemale2   Core.LodMesh   79,421 B
    [10411] SelectionFemale1   Core.LodMesh   89,045 B
    [10412] SelectionMale2     Core.LodMesh   78,873 B
    [10413] SelectionMale1     Core.LodMesh   84,219 B   <- Commando male viewer

`SelectionMale1` (idx 10413):

    MeshOrigin = (-135, 60, 0)      MeshScale = (0.0575, 0.0575, 0.115)
    RotOrigin  = (0, 16384, -16384)
    332 verts / 642 faces / 54 frames, anim seqs: Breath3, Breath2, Breath1
    frame 0 = arms at sides (hands Z ~ -39), toes point +X after world transform

Same vertex/face count as Commando but a separate authored pose - the viewer
pose has no weapon-ready arm. `commando_stand_fit.obj` "looking like holding a
pistol" is the weapon-attach vertex (frame-block idx 1, a special vert NOT
referenced by any wedge, so it never appears in OBJ output) - the arms are fine.

## Export usage

    python3 extract_mesh.py <Botpack.u> <export_idx> --obj <frame> <out.obj> [--fit <scale>]

- Only **wedges** are written as `v` lines (one position per wedge); faces index
  wedges. Special verts (attach points) are never exported.
- Frame-major vert layout: `verts[f * VertexCount + w.iVertex + SpecialVerts]`.
- `--fit <scale>` applies a uniform scale after the import transform (use
  `0.9458` for Commando/Selection Look poses).

## Skeleton overlay in Blender (CRITICAL: 90° yaw)

`GRagdollBoneDefs` are authored in skeleton rest frame: pelvis at origin,
**Z up, arms along +/-X, feet toes +Y**. The mesh world frame after the import
transform has arms along **Y** (not X). To overlay the skeleton boxes on an
exported mesh OBJ, yaw the boxes **+270° about Z**:

    (x, y, z) -> (y, -x, z)

- The body boxes are symmetric under 180°, so +90 vs +270 only flips the feet;
  +270 points toes +X = correct.
- Mesh pelvis lands ~(0,0,0) in world (raw vert nearest `MeshOrigin` maps to
  world ~(0.9,-1.0,1.5)); no extra translation is needed.

## Mesh/animation facts

- All stock player meshes (Commando, Selection*, etc.) are **`Core.LodMesh`
  vertex meshes - there are zero `SkeletalMesh` exports in Botpack.u** even
  though the engine has `USkeletalMesh`. The player viewer uses the same
  LodMesh mechanism.
- Commando (3251): `MeshOrigin=(-150,40,0)`, `MeshScale=(.0625,.0625,.125)`,
  `RotOrigin=(0,16384,-16384)`, 332 verts / 700 frames / 69 anim seqs.
- No Commando animation frame has true arms-down; all standing frames pose arms
  weapon-ready. For arms-down use the Selection* meshes (above).

## Serialization reference (if you touch the parser)

Full field-order spec, encoding gotchas (FCompactIndex, TLazyArray, 25-byte
FBox, **RotOrigin is 3x INT32 in v436**, packed FMeshVert 11/11/10-bit,
frame-major verts, wedge iVertex excludes SpecialVerts) and internal-consistency
anchors are in `format.md`. Validated against export 3251 (leftover == 0).
Standalone blob dumper: `mesh_blob.py`.

## Relevant files

- `extract_mesh.py` - package parser + `ut_rotation_matrix` (fixed),
  `mesh_to_world` (scale-then-rotate), `parse_lod_mesh`, `export_obj --obj`.
- `mesh_blob.py` - field/offset dump of a mesh blob.
- `format.md` - the proven v436 ULodMesh on-disk layout.
- `Core\Inc\UnMath.h:1934` - authoritative `FCoords::operator*=(FRotator)`.
- `RagdollPkg\Src\UnRagdollMesh.cpp` (Ut99PubSrc) - FitScale, capture transform,
  GetFrame coords chain.
- `RagdollPkg\Src\RagdollCarcass.cpp:44-60` (Ut99PubSrc) - `GRagdollBoneDefs`.
