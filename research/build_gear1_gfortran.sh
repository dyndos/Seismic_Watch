#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
GEAR1_ROOT="${GEAR1_ROOT:-$REPO_ROOT/data/external/gear1}"
SOURCE_ROOT="${SOURCE_ROOT:-$GEAR1_ROOT/source}"
BUILD_ROOT="${BUILD_ROOT:-$GEAR1_ROOT/build_gfortran}"
MODE="${1:-full}"

if [[ "$MODE" != "full" && "$MODE" != "diagnostic-step2" ]]; then
  echo "Usage: $0 [full|diagnostic-step2]" >&2
  exit 2
fi

GEAR1_SOURCE="$SOURCE_ROOT/GEAR1_forecast/GEAR1_for_CSEP.f90.txt"
SPHERE_SOURCE="$SOURCE_ROOT/MapTools/Sphere.f90.txt"
if [[ ! -f "$GEAR1_SOURCE" || ! -f "$SPHERE_SOURCE" ]]; then
  echo "Could not find GEAR1 source inputs under: $SOURCE_ROOT" >&2
  echo "Expected: GEAR1_forecast/GEAR1_for_CSEP.f90.txt and MapTools/Sphere.f90.txt" >&2
  exit 1
fi

command -v gfortran >/dev/null || { echo "gfortran is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

mkdir -p "$BUILD_ROOT"
PATCH_ARGS=()
if [[ "$MODE" == "diagnostic-step2" ]]; then
  PATCH_ARGS+=(--stop-after-step2)
fi
python3 "$SCRIPT_DIR/patch_gear1_for_gfortran.py" \
  "$GEAR1_SOURCE" "$SPHERE_SOURCE" "$BUILD_ROOT" "${PATCH_ARGS[@]}"

cp "$SCRIPT_DIR/gear1_mkl_vsl_compat.f90" "$BUILD_ROOT/mkl_vsl_compat.f90"
cd "$BUILD_ROOT"

# The original source has no OpenMP directives. This is a sequential GNU Fortran build.
gfortran -O2 -Wno-aggressive-loop-optimizations -ffree-line-length-none -J . -I . -c mkl_vsl_compat.f90 -o mkl_vsl_compat.o
gfortran -O2 -Wno-aggressive-loop-optimizations -ffree-line-length-none -J . -I . -c Sphere_gfortran.f90 -o Sphere.o
gfortran -O2 -Wno-aggressive-loop-optimizations -ffree-line-length-none -J . -I . -c GEAR1_for_CSEP_gfortran.f90 -o GEAR1_for_CSEP.o

if [[ "$MODE" == "diagnostic-step2" ]]; then
  OUTPUT="gear1_gfortran_step2_diagnostic"
else
  OUTPUT="gear1_gfortran_compat"
fi
gfortran -O2 -o "$OUTPUT" GEAR1_for_CSEP.o Sphere.o mkl_vsl_compat.o

printf '\nBuild completed: %s/%s\n' "$BUILD_ROOT" "$OUTPUT"
printf 'Compiler: %s\n' "$(gfortran --version | head -n 1)"
printf 'NOTICE: standard Fortran RNG replaces Intel MKL VSL; results are not bitwise-identical to the author\x27s Windows executable.\n'
if [[ "$MODE" == "diagnostic-step2" ]]; then
  printf 'This executable stops after STEP #2 and does not create a forecast XML.\n'
fi
