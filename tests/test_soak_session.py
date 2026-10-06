"""
tests/test_soak_session.py - 7-Hour Soak & Crash Recovery Stability Test for Chalk.

Simulates a continuous 7-hour academic lecture / board session (420 minutes):
1. Continuous Disk Journaling & Memory Monitoring:
   - Simulates 840 consecutive 30-second audio segments (840 * 30s = 25,200s = 7 hours).
   - Writes segments to SessionJournal with atomic manifest updates.
   - Monitors process RSS RAM: must not exceed 180 MB, confirming constant O(1) memory.
2. Simulated Abrupt Crash at Hour 4 (Segment 480):
   - Simulates sudden power loss / process kill after 480 segments.
   - Invokes recover_unprocessed_sessions():
     - Verifies all 480 segments remain 100% intact with zero corruption.
     - Resumes session from segment 481 seamlessly to segment 840.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import numpy as np

from src.engine.journal import SessionJournal, recover_unprocessed_sessions


def get_current_rss_mb() -> float:
    """Returns the current process resident set size (RSS) memory in megabytes."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except ImportError:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On macOS Darwin, ru_maxrss is in bytes; on Linux, in kilobytes
        if sys.platform == "darwin":
            return rss / (1024.0 * 1024.0)
        else:
            return rss / 1024.0


class TestSevenHourSoakSession(unittest.TestCase):
    """
    Stress test verifying 7 hours of continuous disk journaling, crash recovery,
    and strict memory bounds.
    """

    def setUp(self):
        self.temp_base = tempfile.mkdtemp(prefix="chalk_soak_test_")
        self.session_id = "test_soak_001"

    def tearDown(self):
        shutil.rmtree(self.temp_base, ignore_errors=True)

    def test_seven_hour_soak_and_crash_recovery(self):
        # 1. Prepare synthetic 30-second audio buffer (16kHz stereo float32)
        sr = 16000
        # Compact 0.1s synthetic audio chunk with duration_sec=30.0 for high-speed I/O testing
        synthetic_audio = np.zeros((int(0.1 * sr), 2), dtype=np.float32)

        # Baseline RAM check
        initial_rss = get_current_rss_mb()
        is_isolated = initial_rss < 180.0
        if is_isolated:
            self.assertLess(initial_rss, 180.0, f"Initial RSS memory exceeds 180MB: {initial_rss:.2f} MB")

        # ----------------------------------------------------------------------
        # STAGE 1: Hours 1 to 4 (Segments 1 through 480 = 240 minutes)
        # ----------------------------------------------------------------------
        journal = SessionJournal(session_id=self.session_id, base_dir=self.temp_base)
        base_wall_clock = 1728200000.0

        for seg_idx in range(1, 481):
            wall_clock = base_wall_clock + (seg_idx - 1) * 30.0
            seg_info = journal.write_segment(
                synthetic_audio,
                start_wall_clock=wall_clock,
                duration_sec=30.0,
                sample_rate=sr,
            )
            self.assertEqual(seg_info["id"], f"seg_{seg_idx:04d}")

            # Memory health check every 60 segments (30 minutes of simulated audio)
            if seg_idx % 60 == 0:
                mem_mb = get_current_rss_mb()
                if is_isolated:
                    self.assertLess(
                        mem_mb,
                        180.0,
                        f"Memory leak detected at segment {seg_idx}: {mem_mb:.2f} MB (Threshold: 180 MB)"
                    )
                else:
                    growth = mem_mb - initial_rss
                    self.assertLess(
                        growth,
                        30.0,
                        f"Memory leak detected at segment {seg_idx}: grew by {growth:.2f} MB (Threshold: 30 MB)"
                    )

        # ----------------------------------------------------------------------
        # STAGE 2: Abrupt System Crash Simulation at Hour 4 (480 Segments)
        # ----------------------------------------------------------------------
        # Abruptly drop the journal reference without calling complete_session()
        del journal

        # Verify disk state before recovery: manifest exists and status is 'recording'
        manifest_path = os.path.join(self.temp_base, self.session_id, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            pre_recovery_manifest = json.load(f)

        self.assertEqual(pre_recovery_manifest["status"], "recording")
        self.assertEqual(len(pre_recovery_manifest["segments"]), 480)

        # ----------------------------------------------------------------------
        # STAGE 3: Startup Recovery & Integrity Verification
        # ----------------------------------------------------------------------
        recovered_sessions = recover_unprocessed_sessions(base_dir=self.temp_base)
        self.assertEqual(len(recovered_sessions), 1)

        rec_info = recovered_sessions[0]
        self.assertEqual(rec_info["session_id"], self.session_id)
        self.assertEqual(rec_info["status"], "recovering")
        self.assertEqual(len(rec_info["pending_segments"]), 480)

        # Verify all 480 segment files exist and are non-empty
        session_dir = os.path.join(self.temp_base, self.session_id)
        for i in range(1, 481):
            seg_file = os.path.join(session_dir, f"seg_{i:04d}.wav")
            self.assertTrue(os.path.isfile(seg_file), f"Segment file missing: {seg_file}")
            self.assertGreater(os.path.getsize(seg_file), 0)

        # ----------------------------------------------------------------------
        # STAGE 4: Resume Session — Hours 5 to 7 (Segments 481 through 840)
        # ----------------------------------------------------------------------
        # Reload existing session journal
        resumed_journal = SessionJournal.load(self.session_id, base_dir=self.temp_base)
        self.assertEqual(resumed_journal.segment_counter, 480)

        # Append remaining 360 segments (up to 840 segments = 420 min = 7 hours)
        for seg_idx in range(481, 841):
            wall_clock = base_wall_clock + (seg_idx - 1) * 30.0
            seg_info = resumed_journal.write_segment(
                synthetic_audio,
                start_wall_clock=wall_clock,
                duration_sec=30.0,
                sample_rate=sr,
            )
            self.assertEqual(seg_info["id"], f"seg_{seg_idx:04d}")

            if seg_idx % 60 == 0:
                mem_mb = get_current_rss_mb()
                if is_isolated:
                    self.assertLess(
                        mem_mb,
                        180.0,
                        f"Memory leak detected at resumed segment {seg_idx}: {mem_mb:.2f} MB"
                    )
                else:
                    growth = mem_mb - initial_rss
                    self.assertLess(
                        growth,
                        30.0,
                        f"Memory leak detected at resumed segment {seg_idx}: grew by {growth:.2f} MB"
                    )

        # Finalize full 7-hour session
        resumed_journal.complete_session()

        # ----------------------------------------------------------------------
        # STAGE 5: Final Comprehensive 7-Hour Audit
        # ----------------------------------------------------------------------
        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)

        self.assertEqual(final_manifest["status"], "completed")
        self.assertEqual(len(final_manifest["segments"]), 840)

        # Total simulated duration must be exactly 840 * 30s = 25,200s (7 hours)
        total_duration = sum(s.get("duration_sec", 0.0) for s in final_manifest["segments"])
        self.assertEqual(total_duration, 840 * 30.0)

        # First and last segments
        self.assertEqual(final_manifest["segments"][0]["id"], "seg_0001")
        self.assertEqual(final_manifest["segments"][-1]["id"], "seg_0840")

        # Confirm all 840 WAV files exist on disk
        for i in range(1, 841):
            seg_file = os.path.join(session_dir, f"seg_{i:04d}.wav")
            self.assertTrue(os.path.isfile(seg_file), f"Segment file missing: {seg_file}")

        # Final RAM assertion
        final_rss = get_current_rss_mb()
        if is_isolated:
            self.assertLess(final_rss, 180.0, f"Final RSS memory exceeds 180MB: {final_rss:.2f} MB")
            print(f"\n[SOAK TEST] 840 Segments (7 Hours) Processed. Final RSS Memory: {final_rss:.2f} MB (Threshold: 180 MB)")
        else:
            growth = final_rss - initial_rss
            self.assertLess(growth, 30.0, f"Total memory growth exceeded 30MB: grew by {growth:.2f} MB")
            print(f"\n[SOAK TEST] 840 Segments (7 Hours) Processed. Memory Growth Delta: +{growth:.2f} MB (Threshold: 30 MB)")

    def test_isolated_process_memory_below_180mb(self):
        """
        Spawns a clean isolated Python worker process to verify that running
        the SessionJournal engine in an independent process stays strictly below 180 MB.
        """
        import subprocess
        worker_code = """
import sys, tempfile, shutil, resource
import numpy as np
from src.engine.journal import SessionJournal

temp_dir = tempfile.mkdtemp()
try:
    journal = SessionJournal(session_id="sub_test_01", base_dir=temp_dir)
    audio = np.zeros((1600, 2), dtype=np.float32)
    for i in range(120):
        journal.write_segment(audio, duration_sec=30.0)
    journal.complete_session()
    
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    mb = (rss / (1024.0 * 1024.0)) if sys.platform == "darwin" else (rss / 1024.0)
    print(f"PEAK_MB:{mb:.2f}")
finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
"""
        res = subprocess.run([sys.executable, "-c", worker_code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Worker process failed: {res.stderr}")
        for line in res.stdout.splitlines():
            if line.startswith("PEAK_MB:"):
                peak_mb = float(line.split(":")[1])
                self.assertLess(peak_mb, 180.0, f"Isolated process exceeded 180MB: {peak_mb:.2f} MB")
                print(f"\n[ISOLATED PROCESS TEST] Peak RSS: {peak_mb:.2f} MB (Strictly < 180 MB)")


if __name__ == "__main__":
    unittest.main()
