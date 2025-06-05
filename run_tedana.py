#!/usr/bin/env python3
"""
Streamlined tedana workflow for processing multi-echo fMRI data from fMRIPrep derivatives.

This script optimally combines multi-echo BOLD images using tedana and applies
spatial transformations to generate outputs in native and MNI space.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import argparse
from nilearn import image
from nibabel.nifti1 import Nifti1Image
from nipype.interfaces.ants import ApplyTransforms
from tedana.workflows import t2smap_workflow


@dataclass
class EchoData:
    """Container for echo-specific data."""

    image: Nifti1Image
    echo_time: float


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
    echoes: List[EchoData]
    transforms: TransformFiles


class TedanaProcessor:
    """Main processor for tedana workflow with improved efficiency."""

    def __init__(
        self, fmriprep_dir: Path, output_dir: Path, subject_id: str, trim_by: int = None
    ):
        self.fmriprep_dir = fmriprep_dir
        self.output_dir = output_dir
        self.subject_id = self._normalize_subject_id(subject_id)
        self.trim_by = trim_by or 0
        self.logger = self._setup_logging()

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

    def _load_echo_data(self, echo_file: Path) -> EchoData:
        """Load echo image and extract echo time."""
        # Load and optionally trim the image
        img = image.load_img(echo_file)
        if self.trim_by > 0:
            img = image.index_img(img, slice(self.trim_by, None))

        # Load echo time from JSON sidecar
        json_file = echo_file.with_suffix("").with_suffix(".json")
        if not json_file.exists():
            raise FileNotFoundError(f"JSON sidecar not found: {json_file}")

        with open(json_file) as f:
            metadata = json.load(f)

        echo_time = metadata.get("EchoTime")
        if echo_time is None:
            raise ValueError(f"EchoTime not found in {json_file}")

        return EchoData(image=img, echo_time=echo_time)

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

        transform_files["t1w_to_mni"] = t1w_to_mni_files[0]

        return TransformFiles(**transform_files)

    def _group_echoes_by_run(self, echo_files: List[Path]) -> Dict[str, RunGroup]:
        """Group echo files by run and load associated data."""
        run_groups = {}

        for echo_file in echo_files:
            # Parse filename components
            components = self._parse_filename_components(echo_file.name)
            run_key = self._create_run_key(components)

            # Load echo data
            echo_data = self._load_echo_data(echo_file)

            # Create or update run group
            if run_key not in run_groups:
                # Only find transform files once per run
                transforms = self._find_transform_files(echo_file)
                run_groups[run_key] = RunGroup(
                    key=run_key, echoes=[], transforms=transforms
                )

            run_groups[run_key].echoes.append(echo_data)

        # Sort echoes by echo time within each run
        for run_group in run_groups.values():
            run_group.echoes.sort(key=lambda x: x.echo_time)

        return run_groups

    def _run_tedana(self, run_group: RunGroup) -> Path:
        """Run tedana on a group of echoes."""
        output_dir = self.output_dir / "tedana_combined" / f"{run_group.key}_rec-tedana"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Extract data and echo times
        data = [echo.image for echo in run_group.echoes]
        echo_times = [echo.echo_time for echo in run_group.echoes]

        self.logger.info(f"Running tedana for {run_group.key} with {len(data)} echoes")
        t2smap_workflow(data, echo_times, out_dir=str(output_dir))

        # Verify output file exists
        optcom_file = output_dir / "desc-optcom_bold.nii.gz"
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
        if output_path.exists():
            self.logger.warning(f"Skipping existing file: {output_path}")
            return output_path

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Applying transforms to create {output_path.name}")

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

        # Validate inputs
        if not self.fmriprep_dir.exists():
            raise ValueError(f"fMRIPrep directory does not exist: {self.fmriprep_dir}")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Find and group echo files
        echo_files = self._find_echo_files()
        run_groups = self._group_echoes_by_run(echo_files)

        # Check that all runs have exactly 3 echoes
        for run_key, run_group in run_groups.items():
            if len(run_group.echoes) != 3:
                raise ValueError(
                    f"Run '{run_key}' must have exactly 3 echoes, but found {len(run_group.echoes)} echoes"
                )

        valid_runs = run_groups

        self.logger.info(f"Processing {len(valid_runs)} runs with 3 echoes each")

        # Process each run
        results = {}
        for run_key, run_group in valid_runs.items():
            # Run tedana
            optcom_file = self._run_tedana(run_group)

            # Apply transformations
            t1w_output, mni_output = self._process_tedana_outputs(
                optcom_file, run_group.transforms, run_key
            )

            results[run_key] = (optcom_file, t1w_output, mni_output)
            self.logger.info(f"Completed processing for {run_key}")

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
