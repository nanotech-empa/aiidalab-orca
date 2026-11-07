"""Conservative array-workspace checks before eigensolver allocations."""


def solver_resources(norb, dimension, nroots, memory_mb, *, dense=False):
    if (
        type(nroots) is not int
        or not 1 <= nroots <= dimension
        or type(memory_mb) is not int
        or memory_mb < 256
    ):
        raise ValueError("Invalid eigensolver root count or memory budget")
    base_space = max(30, 2 * nroots + 4)
    # PySCF davidson1 expands max_space by four vectors per extra root.
    space = base_space + 4 * (nroots - 1)
    tensors = 6 * norb**4
    if dense:
        arrays = 3 * dimension**2 + dimension * (2 * nroots + 8)
    else:
        arrays = dimension * (2 * space + 4 * nroots + 8) + (space + nroots) ** 2
    estimated = 128 + (tensors + arrays) * 8 / 2**20
    if estimated > memory_mb:
        raise ValueError(
            f"Estimated eigensolver workspace {estimated:.1f} MiB exceeds the reviewed {memory_mb} MiB budget; "
            "reduce roots/retained space or increase memory"
        )
    return {
        "estimated_workspace_mib": estimated,
        "memory_limit_mib": memory_mb,
        "davidson_max_space": base_space,
        "solver": "dense selected determinant matrix" if dense else "Davidson",
        "estimate_note": "Conservative array-workspace estimate including Davidson search/images, roots, effective matrix, integral copies and 128 MiB overhead; not an OS memory guarantee.",
    }
