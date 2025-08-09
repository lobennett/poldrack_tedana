#!/bin/bash

# This is the worker script that gets executed by each SLURM array job
# It receives environment variables from the main script

# Check if apptainer image exists (passed from main script)
if [ ! -f "$APPTAINER_IMAGE" ]; then
    echo "Error: Apptainer image not found: $APPTAINER_IMAGE"
    echo "Please ensure the apptainer image path is correct"
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

# Build the command with base arguments
CMD="apptainer exec \"$APPTAINER_IMAGE\" python3 \"$SCRIPT_DIR/run_tedana.py\" \
    --subj-id=\"$SUBJ_ID\" \
    --output-dir=\"$OUTDIR\" \
    --fmriprep-dir=\"$FMRIPREP_DIR\" \
    --apptainer-image=\"$APPTAINER_IMAGE\""

# Add trim_by parameter
if [ "$TRIM_BY" -gt 0 ]; then
    CMD="$CMD --trim-by=\"$TRIM_BY\""
fi

# Add optional flags
if [ -n "$TASK_NAME" ]; then
    CMD="$CMD --task-name=\"$TASK_NAME\""
fi

if [ "$FULL_PIPELINE" = "true" ]; then
    CMD="$CMD --full-pipeline"
fi

if [ "$SKIP_ANTS_TRANSFORM" = "true" ]; then
    CMD="$CMD --skip-ants-transform"
fi

if [ "$USE_FMRIPREP_MASK" = "true" ]; then
    CMD="$CMD --use-fmriprep-mask"
fi

# Execute the command
echo "Running: $CMD"
eval "$CMD"

echo "Completed processing for subject: $SUBJ_ID"