# Poldrack Tedana Utility

A utility package for running tedana multi-echo fMRI processing on SLURM clusters. This package processes fMRIPrep derivatives using tedana and applies spatial transformations to generate outputs in native and MNI space.

## Features

- Parallel processing of multiple subjects using SLURM job arrays
- Automatic detection of subject count for dynamic array sizing
- Works from any directory - can be called as a utility package
- Validates SLURM arguments before job submission
- TR trimming support for removing initial volumes
- Choice between t2smap (fast optimal combination) or full tedana workflow (with denoising)
- Optional use of native space fMRIPrep brain masks for optimal masking
- Generates outputs in T1w and MNI152NLin2009cAsym spaces (optional)

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
   
   This will download the fMRI processing environment container to `./apptainer/poldrack_fmri_latest.sif`.

3. Ensure scripts are executable:
```bash
chmod +x run_tedana.sh run_tedana_worker.sh pull_image.sh
```

## Usage

### Basic Usage

```bash
/path/to/poldrack_tedana/run_tedana.sh <subs_file> <output_dir> <fmriprep_dir> <apptainer_image> [email] [task_name] [trim_by] [full_pipeline] [skip_ants_transform] [use_fmriprep_mask]
```

### Parameters

- `subs_file`: Path to text file containing subject IDs (one per line)
- `output_dir`: Directory where tedana outputs will be saved
- `fmriprep_dir`: Path to fMRIPrep derivatives directory
- `apptainer_image`: Path to apptainer image file (.sif)
- `email` (optional): Email address for SLURM notifications (default: logben@stanford.edu)
- `task_name` (optional): Task name to filter (e.g., 'rest', 'goNogo') (default: all tasks)
- `trim_by` (optional): Number of TRs to trim from beginning (default: 0)
- `full_pipeline` (optional): true/false - Run full tedana workflow with denoising vs t2smap only (default: false)
- `skip_ants_transform` (optional): true/false - Skip ANTs transformations to T1w/MNI space (default: false)
- `use_fmriprep_mask` (optional): true/false - Use fMRIPrep brain mask for tedana (default: false)

### Examples

```bash
# Basic usage - process all tasks with t2smap workflow
/path/to/poldrack_tedana/run_tedana.sh \
    /home/user/subjects.txt \
    /scratch/tedana_output \
    /data/fmriprep \
    /path/to/poldrack_fmri_latest.sif \
    user@stanford.edu

# Process specific task with TR trimming and full tedana pipeline
/path/to/poldrack_tedana/run_tedana.sh \
    subs.txt \
    /scratch/output \
    /oak/.../fmriprep \
    /path/to/poldrack_fmri_latest.sif \
    user@stanford.edu \
    goNogo \
    7 \
    true \
    false

# Process all tasks, trim 7 TRs, full pipeline, skip ANTs transformations, use fMRIPrep mask
/path/to/poldrack_tedana/run_tedana.sh \
    subs.txt \
    /scratch/output \
    /oak/.../fmriprep \
    /path/to/poldrack_fmri_latest.sif \
    logben@stanford.edu \
    "" \
    7 \
    true \
    true \
    true
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
- **CPUs per task**: 2
- **Memory**: 64GB total
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
/path/to/poldrack_tedana/run_tedana.sh subset.txt /output /fmriprep /path/to/image.sif
```

## License

MIT License