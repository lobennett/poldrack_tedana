#!/bin/bash

# Usage: run_tedana.sh <subs_file> <output_dir> <fmriprep_dir> [email]
# Example: run_tedana.sh /path/to/subs.txt /path/to/output /path/to/fmriprep user@email.com

# Check arguments
if [ $# -lt 3 ]; then
    echo "Usage: $0 <subs_file> <output_dir> <fmriprep_dir> [email]"
    echo "Example: $0 /path/to/subs.txt /path/to/output /path/to/fmriprep user@email.com"
    exit 1
fi

# Get script directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
SUBS_FILE="$1"
OUTDIR="$2"
FMRIPREP_DIR="$3"
EMAIL="${4:-logben@stanford.edu}"

# Validate inputs
if [ ! -f "$SUBS_FILE" ]; then
    echo "Error: Subject file does not exist: $SUBS_FILE"
    exit 1
fi

if [ ! -d "$FMRIPREP_DIR" ]; then
    echo "Error: fMRIPrep directory does not exist: $FMRIPREP_DIR"
    exit 1
fi

# Count subjects and set array size
NUM_SUBJECTS=$(wc -l < "$SUBS_FILE")
if [ "$NUM_SUBJECTS" -eq 0 ]; then
    echo "Error: Subject file is empty: $SUBS_FILE"
    exit 1
fi

# Create output and log directories
mkdir -p "$OUTDIR"
mkdir -p "$(dirname "$0")/log"

# Submit job with dynamic array size
sbatch --array=1-$NUM_SUBJECTS \
       --job-name=run_tedana \
       --time=2-00:00:00 \
       --ntasks=1 \
       --cpus-per-task=2 \
       --mem=64GB \
       --partition=russpold,hns,normal \
       --output="${SCRIPT_DIR}/log/%x-%A-%a.out" \
       --error="${SCRIPT_DIR}/log/%x-%A-%a.err" \
       --mail-user="$EMAIL" \
       --mail-type=END \
       --export=SUBS_FILE="$SUBS_FILE",OUTDIR="$OUTDIR",FMRIPREP_DIR="$FMRIPREP_DIR",SCRIPT_DIR="$SCRIPT_DIR" \
       "$SCRIPT_DIR/run_tedana_worker.sh"