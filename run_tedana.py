#!/usr/bin/env python3
"""
Streamlined tedana workflow for processing multi-echo fMRI data from fMRIPrep derivatives.

This script optimally combines multi-echo BOLD images using tedana and applies
spatial transformations to generate outputs in native and MNI space.
"""

import gc
import json
import logging
import psutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import argparse
import nibabel as nib
from nilearn import image
from nibabel.nifti1 import Nifti1Image
from nipype.interfaces.ants import ApplyTransforms
from nipype import config
from tedana.workflows import t2smap_workflow


@dataclass
class EchoFileInfo:
    """Container for echo file path and metadata without loading image."""

    file_path: Path
    echo_time: float
    json_path: Path


@dataclass
class TransformFiles:
    """Container for transformation files shared across runs."""

    bold_to_t1w: Path
    t1w_reference: Path
    mni_reference: Path
    t1w_to_mni: Path


@dataclass
class RunGroup:
    """Container for a group of echoes belonging to the same run."""

    key: str
    echo_files: List[EchoFileInfo]
    transforms: TransformFiles


class TedanaProcessor:
    """Main processor for tedana workflow."""

    def __init__(
        self,
        fmriprep_dir: Path,
        output_dir: Path,
        subject_id: str,
        trim_by: int = None,
        apptainer_image: str = None,
    ):
        self.fmriprep_dir = fmriprep_dir
        self.output_dir = output_dir
        self.subject_id = self._normalize_subject_id(subject_id)
        self.trim_by = trim_by or 0
        self.apptainer_image = apptainer_image
        self.logger = self._setup_logging()

        # Configure nipype to use apptainer if image is provided.
        # NOTE: I added this because there were issues with the 
        # batch submission not accessing ANTS binaries from the container.
        # I'm not sure if this is the best way to handle it though. I might 
        # try something different in the container itself to better expose those paths.
        if self.apptainer_image:
            config.set("execution", "use_relative_paths", True)
            config.set("execution", "stop_on_first_crash", True)

    @staticmethod
    def _normalize_subject_id(subject_id: str) -> str:
        """Ensure subject ID has proper 'sub-' prefix."""
        return subject_id if subject_id.startswith("sub-") else f"sub-{subject_id}"

    @staticmethod
    def _setup_logging() -> logging.Logger:
        """Configure logging for the processor."""
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        return logging.getLogger(__name__)

    def _log_memory_usage(self, stage: str) -> None:
        """Log current memory usage."""
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        self.logger.info(f"Memory usage at {stage}: {memory_mb:.1f} MB")

    def _parse_filename_components(self, filename: str) -> Dict[str, str]:
        """Extract BIDS components from filename."""
        components = filename.split("_")
        return {
            "sub": next((comp for comp in components if comp.startswith("sub-")), None),
            "ses": next((comp for comp in components if comp.startswith("ses-")), None),
            "task": next(
                (comp for comp in components if comp.startswith("task-")), None
            ),
            "run": next((comp for comp in components if comp.startswith("run-")), None),
        }

    def _create_run_key(self, components: Dict[str, str]) -> str:
        """Create a unique key for grouping runs."""
        key_parts = [
            components[k] for k in ["sub", "ses", "task", "run"] if components[k]
        ]
        return "_".join(key_parts)

    def _find_echo_files(self) -> List[Path]:
        """Find all echo files for the subject."""
        subject_dir = self.fmriprep_dir / self.subject_id
        if not subject_dir.exists():
            raise ValueError(f"Subject directory does not exist: {subject_dir}")

        pattern = "*echo-*desc-preproc_bold.nii.gz"
        echo_files = list(subject_dir.glob(f"**/{pattern}"))
        self.logger.info(f"Found {len(echo_files)} echo files for {self.subject_id}")
        return echo_files

    def _get_echo_file_info(self, echo_file: Path) -> EchoFileInfo:
        """Extract echo time from JSON sidecar without loading image."""
        json_file = echo_file.with_suffix("").with_suffix(".json")
        if not json_file.exists():
            raise FileNotFoundError(f"JSON sidecar not found: {json_file}")

        with open(json_file) as f:
            metadata = json.load(f)

        echo_time = metadata.get("EchoTime")
        if echo_time is None:
            raise ValueError(f"EchoTime not found in {json_file}")

        return EchoFileInfo(
            file_path=echo_file, echo_time=echo_time, json_path=json_file
        )

    def _load_echo_image(self, echo_info: EchoFileInfo) -> Nifti1Image:
        """Load and optionally trim a single echo image.s"""
        # Use memory mapping for large files
        img = nib.load(echo_info.file_path, mmap=True)

        if self.trim_by > 0:
            # Convert to nilearn image for trimming, then back to nibabel
            nilearn_img = image.load_img(echo_info.file_path)
            nilearn_img = image.index_img(nilearn_img, slice(self.trim_by, None))
            # Convert back to nibabel format
            img = nib.Nifti1Image(
                nilearn_img.get_fdata(), nilearn_img.affine, nilearn_img.header
            )
            # Clean up intermediate image
            # - Doing this to reduce memory consumption. Before I was struggling with 
            # how much memory executing this script required.
            del nilearn_img 

        return img

    def _find_transform_files(self, echo_file: Path) -> TransformFiles:
        """Find transformation files for a given echo file."""
        base_name = echo_file.name.split("_echo")[0]
        file_dir = echo_file.parent

        # Define file patterns
        patterns = {
            "bold_to_t1w": f"{base_name}_from-boldref_to-T1w_mode-image_desc-coreg_xfm.txt",
            "t1w_reference": f"{base_name}_space-T1w_boldref.nii.gz",
            "mni_reference": f"{base_name}_space-MNI152NLin2009cAsym_res-2_boldref.nii.gz",
        }

        # Find files
        transform_files = {}
        for key, pattern in patterns.items():
            file_path = file_dir / pattern
            if not file_path.exists():
                raise FileNotFoundError(f"Transform file not found: {file_path}")
            transform_files[key] = file_path

        # Find T1w to MNI transform (in anat directory)
        anat_pattern = "*_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5"
        t1w_to_mni_files = list(file_dir.parent.parent.glob(f"**/anat/{anat_pattern}"))
        if not t1w_to_mni_files:
            raise FileNotFoundError(
                f"T1w to MNI transform not found with pattern: {anat_pattern}"
            )

        # TODO: Check there is only one of this
        # - I think this should correctly find the /anat/ fmriprep 
        # directory, but we had troubles with this before. I'll have to 
        # think more about whether this is a robust enough solution.
        transform_files["t1w_to_mni"] = t1w_to_mni_files[0]

        return TransformFiles(**transform_files)

    def _group_echoes_by_run(self, echo_files: List[Path]) -> Dict[str, RunGroup]:
        """Group echo files by run without loading image data."""
        run_groups = {}

        for echo_file in echo_files:
            # Parse filename components
            components = self._parse_filename_components(echo_file.name)
            run_key = self._create_run_key(components)

            # Get echo file info without loading image
            echo_info = self._get_echo_file_info(echo_file)

            # Create or update run group
            if run_key not in run_groups:
                # Only find transform files once per run
                transforms = self._find_transform_files(echo_file)
                run_groups[run_key] = RunGroup(
                    key=run_key, echo_files=[], transforms=transforms
                )

            run_groups[run_key].echo_files.append(echo_info)

        # Sort echoes by echo time within each run
        for run_group in run_groups.values():
            run_group.echo_files.sort(key=lambda x: x.echo_time)

        return run_groups

    def _run_tedana(self, run_group: RunGroup) -> Path:
        """Run tedana on a group of echoes"""
        output_dir = self.output_dir / "tedana_combined" / f"{run_group.key}_rec-tedana"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Check if output already exists
        optcom_file = output_dir / "desc-optcom_bold.nii.gz"
        if optcom_file.exists():
            self.logger.info(
                f"Tedana output already exists for {run_group.key}, skipping"
            )
            return optcom_file

        self._log_memory_usage(f"before tedana {run_group.key}")

        # Load images one at a time and store file paths for tedana
        echo_times = [echo_info.echo_time for echo_info in run_group.echo_files]
        echo_file_paths = [
            str(echo_info.file_path) for echo_info in run_group.echo_files
        ]

        # Apply trimming if needed by creating temporary trimmed files
        if self.trim_by > 0:
            trimmed_files = []
            try:
                for i, echo_info in enumerate(run_group.echo_files):
                    self.logger.info(
                        f"Processing echo {i + 1}/{len(run_group.echo_files)} for trimming"
                    )
                    # Load, trim and save to temp file
                    img = self._load_echo_image(echo_info)
                    temp_file = output_dir / f"temp_echo-{i + 1:02d}_trimmed.nii.gz"
                    nib.save(img, temp_file)
                    trimmed_files.append(str(temp_file))
                    # Explicitly delete image from memory
                    # Again, reducing memory usage here.
                    del img
                    gc.collect()

                self.logger.info(
                    f"Running tedana for {run_group.key} with {len(trimmed_files)} echoes (trimmed)"
                )
                t2smap_workflow(trimmed_files, echo_times, out_dir=str(output_dir))

                # Clean up temporary files
                for temp_file in trimmed_files:
                    Path(temp_file).unlink()

            except Exception as e:
                # Clean up temp files on error
                for temp_file in trimmed_files:
                    if Path(temp_file).exists():
                        Path(temp_file).unlink()
                raise e
        else:
            # Use original files directly with tedana
            self.logger.info(
                f"Running tedana for {run_group.key} with {len(echo_file_paths)} echoes"
            )
            t2smap_workflow(echo_file_paths, echo_times, out_dir=str(output_dir))

        # Force garbage collection
        gc.collect()
        self._log_memory_usage(f"after tedana {run_group.key}")

        # Verify output file exists
        if not optcom_file.exists():
            raise FileNotFoundError(f"Tedana output not found: {optcom_file}")

        return optcom_file

    def _apply_transforms(
        self,
        input_image: Path,
        output_path: Path,
        transforms: List[Path],
        reference: Path,
    ) -> Path:
        """Apply spatial transformations to an image."""
        import os

        if output_path.exists():
            self.logger.warning(f"Skipping existing file: {output_path}")
            return output_path

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Additional check to ensure directory was created successfully
        if not output_path.parent.exists():
            raise RuntimeError(
                f"Failed to create output directory: {output_path.parent}"
            )

        self.logger.info(f"Applying transforms to create {output_path.name}")
        self.logger.info(f"Output directory: {output_path.parent}")
        self.logger.info(f"Directory exists: {output_path.parent.exists()}")
        self.logger.info(
            f"Directory writable: {os.access(output_path.parent, os.W_OK) if output_path.parent.exists() else 'N/A'}"
        )

        if self.apptainer_image:
            # We're already inside the container, so call antsApplyTransforms directly
            import subprocess

            # Update PATH to include ANTs binaries
            current_path = os.environ.get("PATH", "")
            ants_bin_path = "/opt/ants/bin"
            if ants_bin_path not in current_path:
                os.environ["PATH"] = f"{ants_bin_path}:{current_path}"

            # Set LD_LIBRARY_PATH for ANTs libraries
            current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
            ants_lib_path = "/opt/ants/lib"
            if ants_lib_path not in current_ld_path:
                os.environ["LD_LIBRARY_PATH"] = f"{ants_lib_path}:{current_ld_path}"

            # Use the binary name directly since it's now in PATH
            ants_binary = "antsApplyTransforms"

            # Build the command
            cmd = [
                ants_binary,
                "--input",
                str(input_image),
                "--reference-image",
                str(reference),
                "--output",
                str(output_path),
                "--interpolation",
                "LanczosWindowedSinc",
                "--input-image-type",
                "3",
            ]

            # Add transforms
            for transform in transforms:
                cmd.extend(["--transform", str(transform)])

            self.logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                self.logger.error(
                    f"Command failed with return code {result.returncode}"
                )
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"antsApplyTransforms failed: {result.stderr}")

        else:
            # Use nipype interface for local execution
            at = ApplyTransforms()
            at.inputs.input_image = str(input_image)
            at.inputs.reference_image = str(reference)
            at.inputs.output_image = str(output_path)
            at.inputs.interpolation = "LanczosWindowedSinc"
            at.inputs.transforms = [str(t) for t in transforms]
            at.inputs.input_image_type = 3
            at.run()

        return output_path

    def _process_tedana_outputs(
        self, optcom_file: Path, transforms: TransformFiles, run_key: str
    ) -> Tuple[Path, Path]:
        """Apply transformations to tedana outputs."""
        output_base = self.output_dir / "transformed" / run_key

        # T1w space output
        t1w_output = output_base / f"{run_key}_space-T1w_desc-optcom_bold.nii.gz"
        t1w_result = self._apply_transforms(
            input_image=optcom_file,
            output_path=t1w_output,
            transforms=[transforms.bold_to_t1w],
            reference=transforms.t1w_reference,
        )

        # MNI space output
        mni_output = (
            output_base / f"{run_key}_space-MNI152NLin2009cAsym_desc-optcom_bold.nii.gz"
        )
        mni_result = self._apply_transforms(
            input_image=optcom_file,
            output_path=mni_output,
            transforms=[transforms.t1w_to_mni, transforms.bold_to_t1w],
            reference=transforms.mni_reference,
        )

        return t1w_result, mni_result

    def process(self) -> Dict[str, Tuple[Path, Path, Path]]:
        """Main processing pipeline."""
        self.logger.info(f"Processing subject {self.subject_id}")
        self._log_memory_usage("start of processing")

        # Validate inputs
        if not self.fmriprep_dir.exists():
            raise ValueError(f"fMRIPrep directory does not exist: {self.fmriprep_dir}")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Find and group echo files
        echo_files = self._find_echo_files()
        run_groups = self._group_echoes_by_run(echo_files)

        # Check that all runs have exactly 3 echoes
        for run_key, run_group in run_groups.items():
            if len(run_group.echo_files) != 3:
                raise ValueError(
                    f"Run '{run_key}' must have exactly 3 echoes, but found {len(run_group.echo_files)} echoes"
                )

        valid_runs = run_groups

        self.logger.info(f"Processing {len(valid_runs)} runs with 3 echoes each")

        # Process each run sequentially 
        # Better memory usage than loading all these in and then running, as done before.
        results = {}
        for run_key, run_group in valid_runs.items():
            self.logger.info(
                f"Processing run {run_key} ({list(valid_runs.keys()).index(run_key) + 1}/{len(valid_runs)})"
            )

            # Get optimally combined tedana image and run tedana
            optcom_file = self._run_tedana(run_group)

            # Apply transformations
            t1w_output, mni_output = self._process_tedana_outputs(
                optcom_file, run_group.transforms, run_key
            )

            results[run_key] = (optcom_file, t1w_output, mni_output)

            # Force garbage collection between runs
            gc.collect()
            self._log_memory_usage(f"after processing {run_key}")

            self.logger.info(f"Completed processing for {run_key}")

        self._log_memory_usage("end of processing")
        return results


def get_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Streamlined tedana workflow for fMRIPrep derivatives",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--fmriprep-dir", type=Path, required=True, help="Path to fMRIPrep directory"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for tedana derivatives",
    )
    parser.add_argument(
        "--subj-id", type=str, required=True, help="Subject ID to process"
    )
    parser.add_argument(
        "--trim-by",
        type=int,
        default=0,
        help="Number of volumes to trim from beginning",
    )
    parser.add_argument(
        "--apptainer-image",
        type=str,
        help="Path to apptainer image containing ANTs tools",
    )
    return parser


def main():
    """Main entry point."""
    parser = get_parser()
    args = parser.parse_args()

    # Initialize processor
    processor = TedanaProcessor(
        fmriprep_dir=args.fmriprep_dir,
        output_dir=args.output_dir,
        subject_id=args.subj_id,
        trim_by=args.trim_by,
        apptainer_image=args.apptainer_image,
    )

    # Run processing
    try:
        results = processor.process()

        # Log results
        processor.logger.info("Processing completed successfully!")
        for run_key, (optcom, t1w, mni) in results.items():
            processor.logger.info(f"{run_key}:")
            processor.logger.info(f"  Optcom: {optcom}")
            processor.logger.info(f"  T1w: {t1w}")
            processor.logger.info(f"  MNI: {mni}")

    except Exception as e:
        logging.error(f"Processing failed: {e}")
        raise


if __name__ == "__main__":
    main()
