"""Streaming, byte-preserving native Hamiltonian file collection (stdlib only)."""

import re
import shutil
from pathlib import Path


def portable_fcidump(raw, electrons, multiplicity):
    """Keep all integral records verbatim; explicitly declare the target Ms.

    ORCA 6.1.1's tested DumpActInts output writes MS2=0 for open shells too.
    The target sector comes from the checked export input/output, never from
    the spin used to generate the starting orbitals. The raw file is retained.
    """
    header_end = re.search(rb"(?im)^\s*(?:&END|/)\s*$", raw)
    if header_end is None:
        raise ValueError("The native FCIDUMP header is incomplete")
    header = raw[: header_end.end()]

    def number(key):
        values = re.findall(rb"\b" + key + rb"\s*=\s*([+-]?\d+)", header, re.I)
        if len(values) != 1:
            raise ValueError("Missing or ambiguous native header " + key.decode())
        return int(values[0])

    if number(b"NELEC") != electrons:
        raise ValueError(
            "Native FCIDUMP electron count differs from the checked export"
        )
    norb, original = number(b"NORB"), number(b"MS2")
    unpaired = multiplicity - 1
    if (
        type(electrons) is not int
        or type(multiplicity) is not int
        or multiplicity < 1
        or (electrons - unpaired) % 2
        or unpaired > min(electrons, 2 * norb - electrons)
        or original not in (0, unpaired)
    ):
        raise ValueError("Native/target electron and spin sectors are inconsistent")
    corrected = re.sub(
        rb"(\bMS2\s*=\s*)[+-]?\d+",
        lambda match: match[1] + str(unpaired).encode(),
        header,
        count=1,
        flags=re.I,
    )
    portable = corrected + raw[header_end.end() :]
    return portable, {
        "raw_ms2": original,
        "target_ms2": unpaired,
        "alpha_electrons": (electrons + unpaired) // 2,
        "beta_electrons": (electrons - unpaired) // 2,
        "integral_records_changed": False,
        "spin_header_changed": original != unpaired,
    }


def collect(root, electrons, multiplicity):
    """Rewrite only the reviewed spin header; stream every integral byte intact."""
    root = Path(root)
    raw = root / 'aiida.fcidump'
    original = root / 'native_output/aiida.fcidump'
    portable = root / 'native_output/hamiltonian.fcidump'
    if raw.is_symlink() or not raw.is_file() or original.exists() or portable.exists():
        raise ValueError('Missing or unsafe native FCIDUMP')
    raw.replace(original)
    before = original.stat()
    with original.open('rb') as source:
        header = bytearray()
        while True:
            line = source.readline(65537)
            header.extend(line)
            if not line or len(header) > 65536:
                raise ValueError('Native FCIDUMP header is missing or exceeds 64 KiB')
            if re.fullmatch(rb'\s*(?:&END|/)\s*', line, re.I):
                break
        corrected, sector = portable_fcidump(bytes(header), electrons, multiplicity)
        with portable.open('wb') as target:
            target.write(corrected)
            shutil.copyfileobj(source, target, length=1024 * 1024)
    after = original.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Native FCIDUMP changed during collection')
    return original, portable, sector

