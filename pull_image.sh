#!/bin/bash

#SBATCH --job-name=pull_fmri_envs
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=6G
#SBATCH --partition=russpold,hns,normal
#SBATCH --output=./log/pull_image-%j.out
#SBATCH --error=./log/pull_image-%j.err

# Pull apptainer images for fMRI processing

set -e  # Exit on any error

# Configuration
USER=lobennett
APPTAINER_DIR="$(pwd)/apptainer"

# Create apptainer directory if it doesn't exist
mkdir -p "$APPTAINER_DIR"

# Image configurations: IMG_NAME:TAG
IMAGES=(
    "poldrack_fmri:latest"
    "poldrack_fmri:tedana-0.0.12"
)

# Pull each image
for img_tag in "${IMAGES[@]}"; do
    IMG_NAME="${img_tag%:*}"
    TAG="${img_tag#*:}"
    IMAGE_FILE="$APPTAINER_DIR/${IMG_NAME}_${TAG}.sif"
    
    # Check if image already exists
    if [ -f "$IMAGE_FILE" ]; then
        echo "Image already exists: $IMAGE_FILE"
        echo "Skipping download..."
        continue
    fi
    
    echo "Pulling apptainer image..."
    echo "Source: docker://ghcr.io/$USER/$img_tag"
    echo "Destination: $IMAGE_FILE"
    
    # Pull the image
    apptainer pull "$IMAGE_FILE" docker://ghcr.io/$USER/$img_tag
    
    echo "Successfully pulled image to: $IMAGE_FILE"
    echo ""
done

echo "All images processed."