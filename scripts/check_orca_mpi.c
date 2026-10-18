/* Check MPI numeric types used by ORCA, including Fortran types from C. */
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    const int classes[] = {MPI_TYPECLASS_INTEGER, MPI_TYPECLASS_INTEGER,
                           MPI_TYPECLASS_REAL, MPI_TYPECLASS_REAL,
                           MPI_TYPECLASS_COMPLEX, MPI_TYPECLASS_COMPLEX};
    const int sizes[] = {4, 8, 4, 8, 8, 16};
    const char *names[] = {"integer4", "integer8", "real4", "real8",
                           "complex8", "complex16"};
    int rank, ranks, failed = 0, any_failed = 0;

    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &ranks);
    MPI_Comm_set_errhandler(MPI_COMM_WORLD, MPI_ERRORS_RETURN);

    for (int i = 0; i < 6; ++i) {
        MPI_Datatype datatype;
        int actual_size = 0;
        int error = MPI_Type_match_size(classes[i], sizes[i], &datatype);
        if (error == MPI_SUCCESS)
            error = MPI_Type_size(datatype, &actual_size);
        if (error != MPI_SUCCESS || actual_size != sizes[i]) {
            fprintf(stderr, "rank %d: %s unavailable or incorrect\n", rank, names[i]);
            failed = 1;
        } else if (rank == 0) {
            printf("%s: %d bytes\n", names[i], actual_size);
        }
    }

    MPI_Allreduce(&failed, &any_failed, 1, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
    if (rank == 0)
        printf("ORCA MPI numeric types: %s (%d ranks)\n",
               any_failed ? "FAIL" : "PASS", ranks);
    MPI_Finalize();
    return any_failed ? EXIT_FAILURE : EXIT_SUCCESS;
}
