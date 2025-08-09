#!/bin/bash

# Usage: run_tedana.sh <subs_file> <output_dir> <fmriprep_dir> <apptainer_image> [email] [task_name] [trim_by] [full_pipeline] [skip_ants_transform] [use_fmriprep_mask]
# Example: run_tedana.sh /path/to/subs.txt /path/to/output /path/to/fmriprep /path/to/image.sif user@email.com rest 7 true false true

# Check arguments
if [ $# -lt 4 ]; then
    echo "Usage: $0 <subs_file> <output_dir> <fmriprep_dir> <apptainer_image> [email] [task_name] [trim_by] [full_pipeline] [skip_ants_transform] [use_fmriprep_mask]"
    echo "Example: $0 /path/to/subs.txt /path/to/output /path/to/fmriprep /path/to/image.sif user@email.com rest 7 true false true"
    echo ""
    echo "Arguments:"
    echo "  subs_file: Path to file containing subject IDs (one per line)"
    echo "  output_dir: Output directory for tedana derivatives"
    echo "  fmriprep_dir: Path to fMRIPrep derivatives directory"
    echo "  apptainer_image: Path to apptainer image file (.sif)"
    echo "  email: Email for job notifications (default: logben@stanford.edu)"
    echo "  task_name: Task name to filter (e.g., 'rest', 'goNogo') (default: all tasks)"
    echo "  trim_by: Number of TRs to trim from beginning (default: 0)"
    echo "  full_pipeline: true/false (default: false) - Run full tedana workflow with denoising vs t2smap only"
    echo "  skip_ants_transform: true/false (default: false) - Skip ANTs transformations to T1w/MNI space"
    echo "  use_fmriprep_mask: true/false (default: false) - Use fMRIPrep brain mask for tedana"
    exit 1
fi

# Get script directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
SUBS_FILE="$1"
OUTDIR="$2"
FMRIPREP_DIR="$3"
APPTAINER_IMAGE="$4"
EMAIL="${5:-logben@stanford.edu}"
TASK_NAME="${6:-}"
TRIM_BY="${7:-0}"
FULL_PIPELINE="${8:-false}"
SKIP_ANTS_TRANSFORM="${9:-false}"
USE_FMRIPREP_MASK="${10:-false}"

# Validate inputs
if [ ! -f "$SUBS_FILE" ]; then
    echo "Error: Subject file does not exist: $SUBS_FILE"
    exit 1
fi

if [ ! -d "$FMRIPREP_DIR" ]; then
    echo "Error: fMRIPrep directory does not exist: $FMRIPREP_DIR"
    exit 1
fi

if [ ! -f "$APPTAINER_IMAGE" ]; then
    echo "Error: Apptainer image does not exist: $APPTAINER_IMAGE"
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
       --export=SUBS_FILE="$SUBS_FILE",OUTDIR="$OUTDIR",FMRIPREP_DIR="$FMRIPREP_DIR",APPTAINER_IMAGE="$APPTAINER_IMAGE",SCRIPT_DIR="$SCRIPT_DIR",TASK_NAME="$TASK_NAME",TRIM_BY="$TRIM_BY",FULL_PIPELINE="$FULL_PIPELINE",SKIP_ANTS_TRANSFORM="$SKIP_ANTS_TRANSFORM",USE_FMRIPREP_MASK="$USE_FMRIPREP_MASK" \
       "$SCRIPT_DIR/run_tedana_worker.sh"