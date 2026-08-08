"""UT99 (v436) ULodMesh serialized-data field dumper (debug tool).

Usage:  python mesh_blob.py <package.u> <export_index>

Dumps every serialized field of the ULodMesh export with its absolute file
offset, then all parsed values and the leftover check (should be 0). The real
decoder lives in extract_mesh.py (BlobReader + parse_mesh_blob); this script
just walks its field table for manual verification.
"""

import sys

from extract_mesh import UTPackage, parse_mesh_blob


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        sys.exit(2)
    pkg = UTPackage(argv[1])
    exp_idx = int(argv[2])
    e = pkg.exports[exp_idx]
    blob = pkg.data[e.serial_offset:e.serial_offset + e.serial_size]
    res = parse_mesh_blob(pkg, blob, e.serial_offset)
    print(f"== {pkg.name(e.object_name)} export {exp_idx} class={pkg.export_class(exp_idx)} "
          f"size={e.serial_size} off={e.serial_offset}")
    for nm, foff, _ in res["fields"]:
        print(f"{nm:<18} file_off={foff:>9}")
    print("---")
    for k, v in res.items():
        if k == "fields":
            continue
        print(f"{k}: {v}")
    print(f"end_pos={res['end_pos']} blob_size={res['blob_size']} "
          f"leftover={res['blob_size'] - res['end_pos']}")


if __name__ == "__main__":
    main(sys.argv)
