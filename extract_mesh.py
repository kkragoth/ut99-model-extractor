"""UT99 .u package parser + player LODMesh extractor.

Parses the UE1 package file format (UT99) using the exact serialization from the
engine headers (Core\\Inc\\UnLinker.h) plus the FCompactIndex variable-length
integer encoding. Extracts the player LODMesh: verts, faces, wedges, anim
sequences, import transform.

Package summary layout (UnLinker.h FPackageFileSummary):
    INT Tag; INT FileVersion; DWORD PackageFlags;
    INT NameCount, NameOffset;
    INT ExportCount, ExportOffset;
    INT ImportCount, ImportOffset;
    FGuid Guid; TArray<FGenerationInfo> Generations;   // FileVersion>=68

FCompactIndex (from umodel/UnCoreSerialize.cpp):
    read b; sign = b&0x80; r = b&0x3F; shift = 6;
    if (b&0x40): do { read b; r |= (b&0x7F)<<shift; shift += 7 } while (b&0x80);
    value = sign ? -r : r
"""

import struct
import sys
from dataclasses import dataclass, field


def sign_extend(v, bits):
    if v & (1 << (bits - 1)):
        v -= (1 << bits)
    return v


def unpack_fmeshvert(pv):
    # Packed UE1 vertex (SurrealEngine UMesh.cpp): X=11b, Y=11b, Z=10b signed.
    return (sign_extend(pv & 0x7FF, 11),
            sign_extend((pv >> 11) & 0x7FF, 11),
            sign_extend(pv >> 22, 10))


class PackageReader:
    def __init__(self, data, pos):
        self.data = data
        self.pos = pos

    def byte(self):
        v = self.data[self.pos]
        self.pos += 1
        return v

    def int32(self):
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def uint32(self):
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def compact(self):
        b = self.byte()
        sign = b & 0x80
        shift = 6
        r = b & 0x3F
        if b & 0x40:
            while True:
                b = self.byte()
                r |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
        return -r if sign else r


class BlobReader(PackageReader):
    def __init__(self, data, pos=0):
        super().__init__(data, pos)

    def word(self):
        v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def float32(self):
        v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v


def parse_mesh_blob(pkg, blob, base_file_offset):
    """Parse a v436 ULodMesh serialized blob.

    Mirrors gildor2/UEViewer UnMesh1.cpp SerializeLodMesh1 + SurrealEngine
    UMesh.cpp ULodMesh::Load (v436). Returns dict with all fields and per-field
    offsets; `end_pos` should equal blob size (leftover == 0).
    """
    r = BlobReader(blob)
    out = {"fields": []}

    def field(name):
        out["fields"].append((name, r.pos + base_file_offset, r.pos))

    # FName
    name = r.compact()
    out["objName"] = name
    field("objName")

    # FBox
    bb_min = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(3)]
    r.pos += 12
    bb_max = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(3)]
    r.pos += 12
    bb_valid = r.byte()
    out["boundingBox"] = (bb_min, bb_max, bb_valid)
    field("boundingBox")

    # FSphere
    bs = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(4)]
    r.pos += 16
    out["boundingSphere"] = bs
    field("boundingSphere")

    # TLazyArray helpers -------------------------------------------------
    def lazy_array(elem_size, name_):
        skip = r.int32()
        count = r.compact()
        data_pos = r.pos
        r.pos += count * elem_size
        end = r.pos
        out[name_] = {"skip": skip, "count": count,
                      "data_start": data_pos,
                      "file_data_start": data_pos + base_file_offset,
                      "file_data_end": end + base_file_offset,
                      "inline_ok": (skip == end + base_file_offset)}
        field(name_)
        return skip, count

    def plain_array(elem_size, name_):
        count = r.compact()
        data_pos = r.pos
        r.pos += count * elem_size
        out[name_] = {"count": count, "data_start": data_pos}
        field(name_)
        return count

    # Verts
    lazy_array(4, "Verts")
    # Tris
    lazy_array(20, "Tris")
    # AnimSeqs (FMeshAnimSeq: Name, Group, StartFrame, NumFrames, Notifys, Rate)
    an = r.compact()
    aseqs = []
    for _ in range(an):
        nm = r.compact()
        gp = r.compact()
        sf = r.int32()
        nf = r.int32()
        nn = r.compact()
        notifys = []
        for _ in range(nn):
            nt_time = r.float32()
            nt_func = r.compact()
            notifys.append((nt_time, nt_func))
        rt = r.float32()
        aseqs.append({"name": nm, "group": gp, "start": sf,
                      "num": nf, "notifys": notifys, "rate": rt})
    out["AnimSeqs"] = {"count": an, "records": aseqs}
    field("AnimSeqs")
    # Connects
    lazy_array(8, "Connects")
    # BB/BS again
    bb2_min = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(3)]
    r.pos += 12
    bb2_max = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(3)]
    r.pos += 12
    bb2_valid = r.byte()
    out["boundingBox2"] = (bb2_min, bb2_max, bb2_valid)
    field("boundingBox2")
    bs2 = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(4)]
    r.pos += 16
    out["boundingSphere2"] = bs2
    field("boundingSphere2")
    # VertLinks
    lazy_array(4, "VertLinks")
    # Textures (TArray<UTexture*>: each element is a compact FName object ref)
    tn = r.compact()
    tnames = [r.compact() for _ in range(tn)]
    out["Textures"] = {"count": tn, "names": tnames}
    field("Textures")
    # BoundingBoxes
    bn = r.compact()
    r.pos += bn * 25
    out["BoundingBoxes"] = {"count": bn}
    field("BoundingBoxes")
    # BoundingSpheres
    sn = r.compact()
    r.pos += sn * 16
    out["BoundingSpheres"] = {"count": sn}
    field("BoundingSpheres")
    # counts / flags / transforms
    out["VertexCount"] = r.int32()
    field("VertexCount")
    out["FrameCount"] = r.int32()
    field("FrameCount")
    out["AndFlags"] = r.uint32()
    field("AndFlags")
    out["OrFlags"] = r.uint32()
    field("OrFlags")
    out["MeshScale"] = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(3)]
    r.pos += 12
    field("MeshScale")
    out["MeshOrigin"] = [struct.unpack("<f", r.data[r.pos + 4 * i:r.pos + 4 * i + 4])[0] for i in range(3)]
    r.pos += 12
    field("MeshOrigin")
    out["RotOrigin"] = [r.int32(), r.int32(), r.int32()]
    field("RotOrigin")
    out["CurPoly"] = r.int32()
    field("CurPoly")
    out["CurVertex"] = r.int32()
    field("CurVertex")
    # TextureLOD
    if pkg.file_version >= 66:
        tl = r.compact()
        r.pos += tl * 4
        out["TextureLOD"] = {"count": tl}
        field("TextureLOD")
    else:
        out["TextureLOD"] = {"count": None}
    # ULodMesh
    for nm, sz in [("CollapsePointThus", 2), ("FaceLevel", 2), ("Faces", 8),
                   ("CollapseWedgeThus", 2), ("Wedges", 4)]:
        plain_array(sz, nm)
    # Materials (FMeshMaterial = DWORD PolyFlags + INT TextureIndex)
    mn = r.compact()
    mats = []
    for _ in range(mn):
        pf = r.uint32()
        ti = r.int32()
        mats.append((pf, ti))
    out["Materials"] = {"count": mn, "records": mats}
    field("Materials")
    plain_array(8, "SpecialFaces")
    out["ModelVerts"] = r.int32()
    field("ModelVerts")
    out["SpecialVerts"] = r.int32()
    field("SpecialVerts")
    out["MeshScaleMax"] = struct.unpack("<f", r.data[r.pos:r.pos + 4])[0]
    r.pos += 4
    field("MeshScaleMax")
    out["LODHysteresis"] = struct.unpack("<f", r.data[r.pos:r.pos + 4])[0]
    r.pos += 4
    field("LODHysteresis")
    out["LODStrength"] = struct.unpack("<f", r.data[r.pos:r.pos + 4])[0]
    r.pos += 4
    field("LODStrength")
    out["LODMinVerts"] = r.int32()
    field("LODMinVerts")
    out["LODMorph"] = struct.unpack("<f", r.data[r.pos:r.pos + 4])[0]
    r.pos += 4
    field("LODMorph")
    out["LODZDisplace"] = struct.unpack("<f", r.data[r.pos:r.pos + 4])[0]
    r.pos += 4
    field("LODZDisplace")
    plain_array(2, "RemapAnimVerts")
    out["OldFrameVerts"] = r.int32()
    field("OldFrameVerts")
    out["end_pos"] = r.pos
    out["blob_size"] = len(blob)
    return out


@dataclass
class ObjectImport:
    class_package: int
    class_name: int
    package_index: int
    object_name: int


@dataclass
class ObjectExport:
    class_index: int
    super_index: int
    package_index: int
    object_name: int
    object_flags: int
    serial_size: int
    serial_offset: int


@dataclass
class MeshData:
    name: str
    origin: tuple
    scale: tuple
    rot: tuple
    frame_verts: int
    anim_frames: int
    verts: list              # list of (x, y, z) for ALL frames concatenated
    faces: list              # list of (iWedge0, iWedge1, iWedge2, material)
    wedges: list             # list of (iVertex, u, v)
    anim_seqs: list          # list of (name, start_frame, num_frames)
    materials: list          # list of (polyflags, texture_index)
    textures: list = field(default_factory=list)
    special_verts: int = 0   # invisible attachment verts at start of each frame


class UTPackage:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        self._parse_header()
        self._parse_names()
        self._parse_imports()
        self._parse_exports()

    def _parse_header(self):
        r = PackageReader(self.data, 0)
        self.tag = r.uint32()
        self.file_version = r.uint32() & 0xFFFF
        self.package_flags = r.uint32()
        self.name_count = r.uint32()
        self.name_offset = r.uint32()
        self.export_count = r.uint32()
        self.export_offset = r.uint32()
        self.import_count = r.uint32()
        self.import_offset = r.uint32()
        if self.file_version >= 68:
            self.guid = self.data[r.pos:r.pos + 16]
            r.pos += 16
            gen_count = r.uint32()
            self.generations = []
            for _ in range(gen_count):
                e = r.uint32()
                n = r.uint32()
                self.generations.append((e, n))
        else:
            self.guid = None
            self.generations = [(self.export_count, self.name_count)]
        print(f"UT package: tag=0x{self.tag:08X} filever={self.file_version} flags=0x{self.package_flags:08X}")
        print(f"  names={self.name_count} exports={self.export_count} imports={self.import_count} gens={len(self.generations)}")

    def _parse_names(self):
        # Name table at name_offset: inline [len][name\0][flags], len includes NUL.
        names = []
        pos = self.name_offset
        for _ in range(self.name_count):
            if pos >= len(self.data):
                break
            ln = self.data[pos]
            if ln <= 0:
                break
            nm = self.data[pos + 1:pos + 1 + ln - 1].decode("latin-1")
            names.append(nm)
            pos += 1 + ln + 4
        self.names = names

    def _parse_imports(self):
        r = PackageReader(self.data, self.import_offset)
        self.imports = []
        for _ in range(self.import_count):
            cp = r.compact()
            cn = r.compact()
            pk = r.int32()
            on = r.compact()
            self.imports.append(ObjectImport(cp, cn, pk, on))

    def _parse_exports(self):
        r = PackageReader(self.data, self.export_offset)
        self.exports = []
        for _ in range(self.export_count):
            ci = r.compact()
            si = r.compact()
            pi = r.int32()
            on = r.compact()
            of = r.uint32()
            ss = r.compact()
            if ss:
                so = r.compact()
            else:
                so = 0
            self.exports.append(ObjectExport(ci, si, pi, on, of, ss, so))

    def name(self, idx):
        if idx is None:
            return "<none>"
        if isinstance(idx, int):
            if 0 <= idx < len(self.names):
                return self.names[idx]
            return f"<name{idx}>"
        return str(idx)

    def import_name(self, imp_idx):
        if imp_idx < 0:
            i = self.imports[-imp_idx - 1]
            return f"{self.name(i.class_package)}.{self.name(i.object_name)}"
        if imp_idx == 0:
            return "???"
        return self.name(imp_idx)

    def export_class(self, exp_idx):
        e = self.exports[exp_idx]
        if e.class_index >= 0:
            return self.name(e.class_index)  # direct name reference? class is an export
        return self.import_name(e.class_index)


def find_meshes(pkg):
    """Return exports whose class name contains 'Mesh' (LODMesh/VertexMesh)."""
    out = []
    for i, e in enumerate(pkg.exports):
        cn = pkg.export_class(i)
        if "Mesh" in cn:
            out.append((i, e, cn))
    return out


def parse_lod_mesh(pkg, exp_idx):
    """Parse a LodMesh/Mesh export's serialized blob into a MeshData."""
    e = pkg.exports[exp_idx]
    blob = pkg.data[e.serial_offset:e.serial_offset + e.serial_size]
    res = parse_mesh_blob(pkg, blob, e.serial_offset)

    if res["end_pos"] != len(blob):
        raise ValueError(
            f"mesh {exp_idx}: parse left {len(blob) - res['end_pos']} bytes unparsed")

    # Inline Verts (packed int32 per FMeshVert)
    vverts = res["Verts"]
    vert_blob = blob[vverts["data_start"]:vverts["data_start"] + vverts["count"] * 4]
    verts = []
    for i in range(vverts["count"]):
        pv = struct.unpack_from("<I", vert_blob, i * 4)[0]
        verts.append(unpack_fmeshvert(pv))

    # Faces: [iWedge0, iWedge1, iWedge2, MaterialIndex] as _WORDs
    fb = res["Faces"]
    fblob = blob[fb["data_start"]:fb["data_start"] + fb["count"] * 8]
    faces = []
    for i in range(fb["count"]):
        ws = struct.unpack_from("<4H", fblob, i * 8)
        faces.append((ws[0], ws[1], ws[2], ws[3]))

    # Wedges: [_WORD iVertex, _WORD TexUV] (U, V are 2 bytes packed)
    wb = res["Wedges"]
    wblob = blob[wb["data_start"]:wb["data_start"] + wb["count"] * 4]
    wedges = []
    for i in range(wb["count"]):
        ws = struct.unpack_from("<HBB", wblob, i * 4)
        wedges.append((ws[0], ws[1], ws[2]))

    anims = [(a["name"], a["group"], a["start"], a["num"], a["rate"])
             for a in res["AnimSeqs"]["records"]]

    return MeshData(
        name=pkg.name(pkg.exports[exp_idx].object_name),
        origin=res["MeshOrigin"],
        scale=res["MeshScale"],
        rot=res["RotOrigin"],
        frame_verts=res["VertexCount"],
        anim_frames=res["FrameCount"],
        verts=verts,
        faces=faces,
        wedges=wedges,
        anim_seqs=anims,
        materials=res["Materials"]["records"],
        textures=[pkg.name(t) for t in res["Textures"]["names"]],
        special_verts=res["SpecialVerts"],
    )


def ut_rotation_matrix(rot):
    """Build the UT FCoords rotation matrix (UnMath.cpp GMath.Rotation).

    rot = (pitch, yaw, roll) in Unreal rotation units (65536 = 360 deg).
    Returns XAxis, YAxis, ZAxis row vectors; TransformPointBy(V) = V.X*XAxis + V.Y*YAxis + V.Z*ZAxis.
    """
    import math
    cy, sy = math.cos(2 * math.pi * rot[1] / 65536), math.sin(2 * math.pi * rot[1] / 65536)
    cp, sp = math.cos(2 * math.pi * rot[0] / 65536), math.sin(2 * math.pi * rot[0] / 65536)
    cr, sr = math.cos(2 * math.pi * rot[2] / 65536), math.sin(2 * math.pi * rot[2] / 65536)
    xa = (cy * cp, cy * sp * sr - sy * cr, -cy * sp * cr - sy * sr)
    ya = (sy * cp, sy * sp * sr + cy * cr, -sy * sp * cr + cy * sr)
    za = (sp, -cp * sr, cp * cr)
    return xa, ya, za


def mesh_to_world(vert, m):
    """Import transform (UnRagdollMesh.cpp): (vert - Origin) rotated by RotOrigin, then scaled."""
    xa, ya, za = ut_rotation_matrix(m.rot)
    p = (vert[0] - m.origin[0], vert[1] - m.origin[1], vert[2] - m.origin[2])
    r = (p[0] * xa[0] + p[1] * ya[0] + p[2] * za[0],
         p[0] * xa[1] + p[1] * ya[1] + p[2] * za[1],
         p[0] * xa[2] + p[1] * ya[2] + p[2] * za[2])
    return (r[0] * m.scale[0], r[1] * m.scale[1], r[2] * m.scale[2])


def export_obj(pkg, m, out_path, frame=0):
    """Write one frame of the mesh as a Wavefront OBJ (one position per wedge, faces by wedge).

    Wedge iVertex is a MODEL-vert index (excludes SpecialVerts); add SpecialVerts
    to get the index into each frame's vertex block (umodel Wedges[i].iVertex += SpecialVerts).
    Frame verts are laid out frame-major: verts[f * FrameVerts .. (f+1) * FrameVerts).
    """
    world = [mesh_to_world(v, m) for v in m.verts]
    base = frame * m.frame_verts
    with open(out_path, "w") as f:
        f.write(f"# {m.name} frame {frame}/{m.anim_frames} ({len(m.wedges)} wedges, {len(m.faces)} faces)\n")
        for w in m.wedges:
            px, py, pz = world[base + w[0] + m.special_verts]
            f.write(f"v {px:.3f} {py:.3f} {pz:.3f}\n")
        for w in m.wedges:
            f.write(f"vt {w[1] / 255.0:.4f} {w[2] / 255.0:.4f}\n")
        for fa in m.faces:
            f.write(f"f {fa[0] + 1}/{fa[0] + 1} {fa[1] + 1}/{fa[1] + 1} {fa[2] + 1}/{fa[2] + 1}\n")
    print(f"  wrote {out_path} ({len(m.wedges)} verts, {len(m.faces)} faces, frame {frame})")


def main(path):
    pkg = UTPackage(path)
    meshes = find_meshes(pkg)
    print(f"\n=== mesh-like exports ({len(meshes)}) ===")
    for i, e, cn in meshes:
        print(f"  [{i}] {pkg.name(e.object_name)} class={cn} size={e.serial_size} off={e.serial_offset}")

    if len(sys.argv) > 2:
        idx = int(sys.argv[2])
    else:
        idx = meshes[0][0]
    m = parse_lod_mesh(pkg, idx)
    print(f"\n=== mesh [{idx}] {m.name} ===")
    print(f"  frame_verts={m.frame_verts} anim_frames={m.anim_frames} "
          f"faces={len(m.faces)} wedges={len(m.wedges)} materials={len(m.materials)}")
    print(f"  origin={m.origin} scale={m.scale} rot={m.rot}")
    print(f"  textures={m.textures}")
    print(f"  anim_seqs={len(m.anim_seqs)} first={[pkg.name(a[0]) for a in m.anim_seqs[:8]]}")
    print(f"  first verts={m.verts[:5]}")
    print(f"  first faces={m.faces[:5]}")
    print(f"  first wedges={m.wedges[:5]}")
    lo = [min(v[0] for v in m.verts), min(v[1] for v in m.verts), min(v[2] for v in m.verts)]
    hi = [max(v[0] for v in m.verts), max(v[1] for v in m.verts), max(v[2] for v in m.verts)]
    print(f"  vert bbox min={lo} max={hi}")

    if len(sys.argv) > 3 and sys.argv[3] == "--obj":
        frame = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].lstrip("-").isdigit() else 0
        out = sys.argv[5] if len(sys.argv) > 5 else "mesh.obj"
        export_obj(pkg, m, out, frame=frame)


if __name__ == "__main__":
    main(sys.argv[1])
