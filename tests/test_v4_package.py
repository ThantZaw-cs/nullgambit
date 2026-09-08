"""Release packaging must select the frozen candidate, never the root legacy agent."""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import validate_v4


class FrozenPackageTests(unittest.TestCase):
    def test_archive_contains_only_the_exact_frozen_candidate_and_license(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / "extracted"
            archive = root / "candidate.zip"
            validate_v4.package(archive, extracted)
            with zipfile.ZipFile(archive) as packed:
                self.assertEqual(packed.namelist(), ["agent.py", "LICENSE"])
            self.assertEqual(
                validate_v4.digest(extracted / "agent.py"), validate_v4.CANDIDATE_SHA256
            )
            self.assertNotEqual(
                (extracted / "agent.py").read_bytes(), (validate_v4.ROOT / "agent.py").read_bytes()
            )

    def test_wrong_source_is_rejected_before_an_archive_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prototypes/numba_kernel/agent.py"
            source.parent.mkdir(parents=True)
            source.write_bytes((validate_v4.ROOT / "agent.py").read_bytes())
            archive = root / "candidate.zip"
            with (
                patch.object(validate_v4, "ROOT", root),
                self.assertRaisesRegex(RuntimeError, "Frozen v4 source hash mismatch"),
            ):
                validate_v4.package(archive, root / "extracted")
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
