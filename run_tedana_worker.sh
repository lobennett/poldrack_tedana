#!/bin/bash

# This is the worker script that gets executed by each SLURM array job
# It receives environment variables from the main script

# Check if apptainer image exists
APPTAINER_IMAGE="$SCRIPT_DIR/apptainer/fmri_env_latest.sif"
if [ ! -f "$APPTAINER_IMAGE" ]; then
    echo "Error: Apptainer image not found: $APPTAINER_IMAGE"
    echo "Please run the pull_image.sh script first to download the required image:"
    echo "  $SCRIPT_DIR/pull_image.sh"
    exit 1
fi

echo "Using apptainer image: $APPTAINER_IMAGE"

# Get subject ID from the line number corresponding to SLURM_ARRAY_TASK_ID
SUBJ_ID=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$SUBS_FILE")

if [ -z "$SUBJ_ID" ]; then
    echo "Error: Could not get subject ID for array task $SLURM_ARRAY_TASK_ID"
    exit 1
fi

echo "Processing subject: $SUBJ_ID (Array task: $SLURM_ARRAY_TASK_ID)"

# Run tedana using apptainer with the Python script from the same directory as this worker script
apptainer exec "$APPTAINER_IMAGE" python3 "$SCRIPT_DIR/run_tedana.py" \
    --subj-id="$SUBJ_ID" \
    --output-dir="$OUTDIR" \
    --fmriprep-dir="$FMRIPREP_DIR" \
    --apptainer-image="$APPTAINER_IMAGE"

echo "Completed processing for subject: $SUBJ_ID"