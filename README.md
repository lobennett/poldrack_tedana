# Poldrack Tedana Utility

A utility package for running tedana multi-echo fMRI processing on SLURM clusters. This package processes fMRIPrep derivatives using tedana and applies spatial transformations to generate outputs in native and MNI space.

## Features

- Parallel processing of multiple subjects using SLURM job arrays
- Automatic detection of subject count for dynamic array sizing
- Works from any directory - can be called as a utility package
- Validates SLURM arguments before job submission
- Generates outputs in T1w and MNI152NLin2009cAsym spaces

## Prerequisites

- SLURM cluster environment
- Apptainer/Singularity container runtime
- fMRIPrep derivatives with multi-echo BOLD data

## Installation

1. Clone this repository:
```bash
git clone https://github.com/lobennett/poldrack_tedana.git
cd poldrack_tedana
```

2. **Pull the required apptainer image** (this step is required before running the pipeline):

   **Option A - Direct execution:**
   ```bash
   ./pull_image.sh
   ```
   
   **Option B - SLURM batch submission:**
   ```bash
   sbatch pull_image.sh
   ```
   
   This will download the fMRI processing environment container to `./apptainer/fmri_env_latest.sif`.

3. Ensure scripts are executable:
```bash
chmod +x run_tedana.sh run_tedana_worker.sh pull_image.sh
```

## Usage

### Basic Usage

```bash
/path/to/poldrack_tedana/run_tedana.sh <subs_file> <output_dir> <fmriprep_dir> [email]
```

### Parameters

- `subs_file`: Path to text file containing subject IDs (one per line)
- `output_dir`: Directory where tedana outputs will be saved
- `fmriprep_dir`: Path to fMRIPrep derivatives directory
- `email` (optional): Email address for SLURM notifications (defaults to mine, logben@stanford.edu)

### Example

```bash
# Process subjects from a file
/path/to/poldrack_tedana/run_tedana.sh \
    /home/user/subjects.txt \
    /scratch/tedana_output \
    /data/fmriprep \
    user@stanford.edu
```

### Subject File Format

Create a text file with one subject ID per line:
```
s01
s02
s03
```

Subject IDs can be with or without the "sub-" prefix (the script handles both formats).

## Output Structure

The script generates the following output structure:

```
output_dir/
├── tedana_combined/
│   └── sub-{id}_ses-{ses}_task-{task}_run-{run}_rec-tedana/
│       ├── desc-optcom_bold.nii.gz # optimally combined tedana image
│       └── [other tedana outputs]
└── transformed/
    └── sub-{id}_ses-{ses}_task-{task}_run-{run}/
        ├── sub-{id}_ses-{id}_task-{task}_run-{run}_space-T1w_desc-optcom_bold.nii.gz
        └── sub-{id}_ses-{id}_task-{task}_run-{run}_space-MNI152NLin2009cAsym_desc-optcom_bold.nii.gz
```

## SLURM Configuration

The script submits jobs with the following default settings:
- **Time limit**: 2 days
- **CPUs per task**: 8
- **Memory**: 8GB per CPU
- **Partitions**: russpold, hns, normal
- **Array size**: Automatically set based on number of subjects

## Logs

Job logs are saved in the `log/` directory within the script's location:
- `log/run_tedana-{job_id}-{array_id}.out`
- `log/run_tedana-{job_id}-{array_id}.err`

## Requirements

### Input Data Requirements

- Multi-echo BOLD data preprocessed with fMRIPrep
- Exactly 3 echoes per run
- Required transformation files:
  - `*_from-boldref_to-T1w_mode-image_desc-coreg_xfm.txt`
  - `*_space-T1w_boldref.nii.gz`
  - `*_space-MNI152NLin2009cAsym_res-2_boldref.nii.gz`
  - `*_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5`

### Python Dependencies

All dependencies are managed within the apptainer container. The container includes:
- nibabel
- nipype
- tedana
- ANTs
- All other required Python packages

## Troubleshooting

### Common Issues

1. **"Subject file does not exist"**: Verify the path to your subjects file
2. **"fMRIPrep directory does not exist"**: Check the fMRIPrep path
3. **"Subject file is empty"**: Ensure your subjects file contains at least one subject ID
4. **Job fails with missing echoes**: Verify your data has exactly 3 echoes per run

### Checking Job Status

```bash
# Check job status
squeue -u $USER

# View job output
cat log/run_tedana-{job_id}-{array_id}.out

# View job errors
cat log/run_tedana-{job_id}-{array_id}.err
```

## Advanced Usage

### Custom SLURM Parameters

To modify SLURM parameters, edit the `sbatch` command in `run_tedana.sh`:

```bash
sbatch --array=1-$NUM_SUBJECTS \
       --job-name=run_tedana \
       --time=02:00:00 \          # Reduce time limit
       --cpus-per-task=16 \       # More CPUs
       --mem-per-cpu=16G \        # More memory
       # ... other parameters
```

### Processing Subset of Subjects

Create a subjects file with only the subjects you want to process:

```bash
# Process only first 5 subjects
head -5 all_subjects.txt > subset.txt
/path/to/poldrack_tedana/run_tedana.sh subset.txt /output /fmriprep
```

## License

MIT License